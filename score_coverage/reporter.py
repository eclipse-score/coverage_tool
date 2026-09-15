#!/usr/bin/env python3
# *******************************************************************************
# Copyright (c) 2026 Contributors to the Eclipse Foundation
#
# See the NOTICE file(s) distributed with this work for additional
# information regarding copyright ownership.
#
# This program and the accompanying materials are made available under the
# terms of the Apache License Version 2.0 which is available at
# https://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0
# *******************************************************************************
"""Final coverage report generator using llvm-cov.

This script is invoked by Bazel as the --coverage_report_generator after all tests
complete. It reads the per-test zip files produced by the merger, merges all profdata
into one, and generates the final combined HTML report.

Expected Bazel interface:
    --reports_file=<path>    Text file listing paths to all per-test coverage outputs
    --output_file=<path>     Where to write the final report (zip)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from python.runfiles import Runfiles


class RunfilesLike(Protocol):
    """The part of ``python.runfiles.Runfiles`` this module uses; tests provide fakes."""

    def Rlocation(self, path: str) -> str | None:  # noqa: N802  # pylint: disable=invalid-name
        """Resolve a runfiles path to an absolute path, or None."""


def main(argv: list[str] | None = None) -> None:
    """Main entry point. ``argv`` defaults to ``sys.argv[1:]``."""
    args = parse_args(argv)
    r = Runfiles.Create()
    if r is None:
        print("ERROR: runfiles are unavailable; the reporter must run as a Bazel coverage action.", file=sys.stderr)
        sys.exit(1)

    # Read the list of per-test report files.
    reports = read_reports_file(args.reports_file)
    if not reports:
        print("INFO: No coverage reports listed; writing empty output.", file=sys.stderr)
        write_empty_output(args.output_file)
        return

    # Extract profdata and object files from each per-test zip.
    valid_profdata_files, valid_object_files = extract_reports(reports)

    if not valid_profdata_files or not valid_object_files:
        print("INFO: No valid profdata or object files found; writing empty output.", file=sys.stderr)
        write_empty_output(args.output_file)
        return

    sorted_objects = sorted(valid_object_files)

    # Resolve the llvm tools. The reporter_wrapper passes explicit rlocation
    # paths for the consumer-supplied toolchain labels; the bare
    # "llvm_toolchain/..." forms remain as a fallback for in-repo setups.
    llvm_bin_path = resolve_tool(r, args.llvm_cov, "llvm_toolchain/llvm-cov")
    llvm_profdata_path = resolve_tool(r, args.llvm_profdata, "llvm_toolchain/llvm-profdata")
    if not llvm_bin_path or not llvm_profdata_path:
        print(
            "ERROR: llvm-cov/llvm-profdata not found in runfiles. Pass --llvm_cov "
            "and --llvm_profdata (the score_coverage_reporter macro does this).",
            file=sys.stderr,
        )
        sys.exit(1)

    # Merge all per-test profdata files.
    merged_profdata = Path.cwd() / "merged_coverage.profdata"
    merge_inputs = sorted(set(valid_profdata_files))
    run_command(
        [
            str(llvm_profdata_path),
            "merge",
            "--output",
            str(merged_profdata),
        ]
        + merge_inputs
    )

    # Load baseline objects (production library archives) for zero-coverage baseline.
    # Load baseline objects (production library archives) for zero-coverage
    # baseline. llvm-cov rejects an archive as a whole when one member lacks
    # a coverage mapping (the lib.rmeta of a Rust rlib, the object of an empty
    # translation unit), so such archives are replaced by their usable members.
    baseline_manifest = load_baseline_manifest(r, args.baseline_objects)
    baseline_objects, empty_stems = expand_baseline_archives(baseline_manifest, Path.cwd() / "baseline_objects")

    selection, path_map, root, regexes = prepare_sources(
        r, args, llvm_bin_path, sorted_objects, str(merged_profdata), baseline_objects, empty_stems
    )
    # All valid baseline archives are passed when baseline-only files exist;
    # _filter_lcov keeps only those files' records.
    baseline_only_archives = list(baseline_objects) if selection.baseline_only else []

    cxxfilt = find_cxxfilt(llvm_bin_path, r, args.llvm_cxxfilt)
    profile = str(merged_profdata)

    def show_html(objects: list[str]) -> None:
        run_llvm_cov_show(
            llvm_bin_path,
            objects,
            profile,
            regexes,
            root,
            output_format="html",
            html_report_dir=html_report_dir,
            cxxfilt=cxxfilt,
        )

    # Generate HTML report including baseline-only files when valid archives are available.
    html_report_dir = Path.cwd() / "html_report"
    if baseline_only_archives:
        try:
            show_html(sorted_objects + baseline_only_archives)
        except SystemExit:
            # Some baseline archives caused llvm-cov show to fail; retry with test binaries only.
            print(
                "WARNING: HTML generation with baseline archives failed; falling back to test-only HTML.",
                file=sys.stderr,
            )
            show_html(sorted_objects)
    else:
        show_html(sorted_objects)

    # File the pages under canonical, machine-independent paths so the index
    # links resolve wherever the archive is unpacked, and name the sources
    # the same way in the page titles.
    relocate_html_pages(html_report_dir, root, path_map)
    _make_html_paths_relative(html_report_dir, root, path_map)

    # Generate LCOV report from test binaries.
    lcov_report_dir = Path.cwd() / "lcov_report"
    lcov_report_dir.mkdir(exist_ok=True)
    lcov_content = _make_lcov_paths_relative(
        run_llvm_cov_export(llvm_bin_path, sorted_objects, profile, regexes, root).stdout, root, path_map
    )

    # If there are baseline-only files, generate a separate baseline LCOV and merge.
    if baseline_only_archives:
        # No filtering: only the needed archives are passed.
        baseline_lcov = run_llvm_cov_export(llvm_bin_path, baseline_only_archives, None, [], root)
        if baseline_lcov.stdout:
            # Filter baseline LCOV to only include baseline-only files.
            filtered_baseline = _filter_lcov(
                _make_lcov_paths_relative(baseline_lcov.stdout, root, path_map), selection.baseline_only
            )
            if filtered_baseline:
                lcov_content += filtered_baseline
                print(f"INFO: Merged baseline LCOV for {len(selection.baseline_only)} files.", file=sys.stderr)

    with open(lcov_report_dir / "lcov.dat", "w", encoding="utf-8") as f:
        f.write(lcov_content)

    # Generate text summary.
    text_report_dir = Path.cwd() / "text_report"
    text_report_dir.mkdir(exist_ok=True)
    summary = run_llvm_cov_report(llvm_bin_path, sorted_objects, profile, regexes, root)
    summary_text = _canonicalize_summary(summary.stdout, root, path_map)
    with open(text_report_dir / "summary.txt", "w", encoding="utf-8") as f:
        f.write(summary_text)
    print(summary_text, file=sys.stderr)
    # Always written, so consumers can rely on the file: "<category>\t<path>"
    # per line, empty when every in-scope file has coverage data.
    with open(text_report_dir / "unmapped_files.txt", "w", encoding="utf-8") as f:
        f.write(format_unmapped_files(selection))

    # Package everything into the output zip.
    directories = [html_report_dir, lcov_report_dir, text_report_dir]
    create_zip(
        root=Path.cwd(),
        directories=directories,
        output_file=args.output_file,
    )

    print(f"INFO: Coverage reporter completed. Output: {args.output_file}", file=sys.stderr)


# Configuration-specific root of a generated file's exec path, e.g.
# "bazel-out/k8-fastbuild/bin/" or "bazel-out/k8-opt-exec-ST-<hash>/bin/". Headers
# behind strip_include_prefix are compiled from such a _virtual_includes/ tree
# and the coverage mapping records that path; the scope allowlist carries the
# configuration-agnostic short_path, so both sides are normalized to it.
_BAZEL_OUT_CONFIG_RE = re.compile(r"^bazel-out/[^/]+/bin/")


def strip_config_prefix(path: str) -> str:
    """Drop a leading ``bazel-out/<config>/bin/`` from a workspace-relative path."""
    return _BAZEL_OUT_CONFIG_RE.sub("", path, count=1)


def redundant_baseline_variants(test_covered: dict[str, str], baseline_covered: dict[str, str]) -> set[str]:
    """Raw baseline paths whose normalized file is already covered by a test binary.

    Both dicts map raw covmap paths to normalized names. A plain source file
    has the same raw path in both, so nothing is returned for it; a generated
    header differs only in the configuration prefix, and its baseline variant
    would otherwise appear as a second, spurious 0 % entry.
    """
    covered_names = set(test_covered.values())
    return {raw for raw, name in baseline_covered.items() if name in covered_names and raw not in test_covered}


def canonical_path(path: str, path_map: dict[str, str] | None = None) -> str:
    """The name a file is reported under.

    Drops the configuration prefix of a generated header and maps a
    ``_virtual_includes/`` path to the header it was generated from (the
    scope's path map). Plain source paths are returned unchanged.
    """
    stripped = strip_config_prefix(path)
    if path_map:
        return path_map.get(stripped, stripped)
    return stripped


def exclusion_regex(raw: str, roots: list[str]) -> str:
    """``--ignore-filename-regex`` that matches exactly one compiled file.

    ``raw`` is the file's covmap path with the compilation directory
    stripped (``src/a.cpp``, ``bazel-out/<cfg>/bin/.../x.h``). llvm-cov
    matches the filter against the name joined with the recorded
    compilation directory (``/proc/self/cwd/<raw>``) or with the
    ``--compilation-dir`` we pass (``<root>/<raw>``); a Rust file may also
    appear bare. Anchoring on both ends keeps an excluded ``foo/bar.h`` from
    also suppressing an in-scope ``src/foo/bar.h``. llvm-cov uses POSIX
    extended regular expressions: no ``(?:`` groups.
    """
    prefixes = ["/proc/self/cwd/"] + [root.rstrip("/") + "/" for root in roots]
    return "^(" + "|".join(re.escape(prefix) for prefix in prefixes) + ")?" + re.escape(raw) + "$"


def duplicate_test_variants(test_covered: dict[str, str]) -> dict[str, list[str]]:
    """Raw test-binary paths to drop because another raw path of the same file is kept.

    A file compiled under two names (its declared path and a virtual-includes
    path) would otherwise produce two entries for one canonical name. The
    variant equal to the canonical name is kept, else the first in sort order.
    Returns {canonical name: dropped raw paths}.
    """
    by_name: dict[str, list[str]] = {}
    for raw, name in sorted(test_covered.items()):
        by_name.setdefault(name, []).append(raw)
    dropped: dict[str, list[str]] = {}
    for name, raws in by_name.items():
        if len(raws) > 1:
            keep = name if name in raws else raws[0]
            dropped[name] = [raw for raw in raws if raw != keep]
    return dropped


@dataclass
class FileSelection:
    """Which compiled files stay in the report and under which name."""

    staged: dict[str, str] = field(default_factory=dict)
    """raw covmap path -> canonical name of every file that stays in the report."""
    excluded: set[str] = field(default_factory=set)
    """raw covmap paths suppressed through --ignore-filename-regex."""
    baseline_only: set[str] = field(default_factory=set)
    """canonical names that only the baseline archives contain (0 % entries)."""
    duplicates: dict[str, list[str]] = field(default_factory=dict)
    """canonical name -> raw variants dropped in favour of another variant."""
    unmapped: set[str] = field(default_factory=set)
    """allowlisted files without coverage data anywhere, and no benign explanation: the findings."""
    declaration_only: set[str] = field(default_factory=set)
    """unmapped headers whose same-named source file has coverage data (declarations only)."""
    empty_units: set[str] = field(default_factory=set)
    """unmapped sources that were compiled into a baseline archive but produced no coverage mapping."""


_HEADER_SUFFIXES = (".h", ".hpp", ".hh", ".hxx", ".inl", ".ipp", ".tpp")


def _is_header(path: str) -> bool:
    return path.endswith(_HEADER_SUFFIXES)


def _stem(path: str) -> str:
    """Path without its last extension: ``src/foo.h`` and ``src/foo.cpp`` share ``src/foo``."""
    return os.path.splitext(path)[0]


def select_files(
    test_covered: dict[str, str],
    baseline_covered: dict[str, str],
    allowlist: set[str] | None,
    empty_stems: set[str] | None = None,
) -> FileSelection:
    """Apply the scope allowlist to the raw files of test binaries and baseline archives.

    ``allowlist`` is a set of canonical names; ``None`` keeps every file.
    ``empty_stems`` are ``<dir>/<name>`` stems of baseline archive members
    that carry no coverage mapping (see :func:`expand_baseline_archives`); an
    allowlisted source with such a stem was compiled and holds no code.
    """
    everything = {**baseline_covered, **test_covered}

    def in_scope(name: str) -> bool:
        return allowlist is None or name in allowlist

    excluded = {raw for raw, name in everything.items() if not in_scope(name)}
    excluded |= redundant_baseline_variants(test_covered, baseline_covered)
    duplicates = duplicate_test_variants(test_covered)
    for raws in duplicates.values():
        excluded.update(raws)
    staged = {raw: name for raw, name in everything.items() if raw not in excluded}
    baseline_only = {name for name in set(baseline_covered.values()) - set(test_covered.values()) if in_scope(name)}
    # In scope, but compiled into nothing: a header no translation unit
    # includes, or template code that is never instantiated. llvm-cov cannot
    # report such a file, not even at 0 %, so the reporter must.
    unmapped: set[str] = set()
    declaration_only: set[str] = set()
    empty_units: set[str] = set()
    if allowlist is not None:
        with_data = set(test_covered.values()) | set(baseline_covered.values())
        unmapped = allowlist - with_data
        # A header whose same-named source file has data (foo.h next to a
        # compiled foo.cpp) holds declarations only; that is expected and is
        # kept apart from headers nothing compiles.
        stems_with_data = {_stem(name) for name in with_data}
        declaration_only = {name for name in unmapped if _is_header(name) and _stem(name) in stems_with_data}
        unmapped -= declaration_only
        # A source whose object sits in a baseline archive without a coverage
        # mapping is an empty translation unit (a placeholder .cpp of a
        # header-only library): compiled, nothing to cover.
        if empty_stems:
            empty_units = {name for name in unmapped if not _is_header(name) and _stem(name) in empty_stems}
            unmapped -= empty_units
    return FileSelection(
        staged=staged,
        excluded=excluded,
        baseline_only=baseline_only,
        duplicates=duplicates,
        unmapped=unmapped,
        declaration_only=declaration_only,
        empty_units=empty_units,
    )


UNMAPPED_NO_DATA = "no-data"
UNMAPPED_DECLARATION_ONLY = "declaration-only"
UNMAPPED_EMPTY_UNIT = "empty-translation-unit"


def format_unmapped_files(selection: FileSelection) -> str:
    """``<category>\t<path>`` lines for every in-scope file without coverage data."""
    rows = (
        [(UNMAPPED_NO_DATA, name) for name in selection.unmapped]
        + [(UNMAPPED_DECLARATION_ONLY, name) for name in selection.declaration_only]
        + [(UNMAPPED_EMPTY_UNIT, name) for name in selection.empty_units]
    )
    return "".join(f"{category}\t{name}\n" for category, name in sorted(rows))


def resolve_source(runfiles: RunfilesLike, canonical: str, workspace_root: str) -> str | None:
    """Absolute path of an in-scope source: from the reporter's runfiles, else the workspace."""
    if canonical.startswith("external/"):
        candidates = [runfiles.Rlocation(canonical[len("external/") :])]
    else:
        candidates = [runfiles.Rlocation(os.path.join("_main", canonical)), os.path.join(workspace_root, canonical)]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def stage_sources(
    source_root: Path,
    staged: dict[str, str],
    runfiles: RunfilesLike,
    workspace_root: str,
) -> list[str]:
    """Create ``source_root/<raw covmap path>`` links to the real sources.

    llvm-cov then reads every in-scope file through one
    ``--path-equivalence=/proc/self/cwd/,<source_root>`` (C++) and
    ``--compilation-dir=<source_root>`` (Rust). Returns the canonical names
    whose source could not be located.
    """
    missing = []
    for raw, canonical in sorted(staged.items()):
        if raw.startswith("/"):
            continue  # an absolute covmap path is read as it is
        real = resolve_source(runfiles, canonical, workspace_root)
        if real is None:
            missing.append(canonical)
            continue
        link = source_root / raw
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink() and not link.exists():
            link.symlink_to(os.path.realpath(real))
    return sorted(set(missing))


_ASSET_LINK_RE = re.compile(r"((?:href|src)=')((?:\.\./)*)(style\.css|control\.js)'")


def _retarget_assets(text: str, depth: int) -> str:
    """Point a page's style.css / control.js links ``depth`` directories up."""
    up = "../" * depth
    return _ASSET_LINK_RE.sub(lambda m: m.group(1) + up + m.group(3) + "'", text)


def relocate_html_pages(html_dir: Path, source_root: str, path_map: dict[str, str] | None = None) -> dict[str, str]:
    """Move llvm-cov's pages from ``coverage/<source_root>/<raw>.html`` to ``coverage/<canonical>.html``.

    llvm-cov files each page under the absolute path it read the source from.
    After the move the archive contains no machine-specific paths, every
    index link points at a page that exists, and a header behind an include
    prefix is filed under its declared path. Returns {old href: new href}.
    """
    coverage_dir = html_dir / "coverage"
    root_rel = source_root.strip("/")
    base = coverage_dir / root_rel
    moves: dict[str, str] = {}
    for page in sorted(base.rglob("*.html")) if base.is_dir() else []:
        raw = page.relative_to(base).as_posix()[: -len(".html")]
        canonical = canonical_path(raw, path_map)
        target = coverage_dir / (canonical + ".html")
        if target.exists():
            print(f"WARNING: {canonical} was rendered twice; keeping the first page", file=sys.stderr)
            page.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            page.rename(target)
            text = target.read_text(encoding="utf-8", errors="replace")
            target.write_text(_retarget_assets(text, canonical.count("/") + 1), encoding="utf-8")
        moves[f"coverage/{root_rel}/{raw}.html"] = f"coverage/{canonical}.html"
    shutil.rmtree(base, ignore_errors=True)
    parent = base.parent
    while parent != coverage_dir:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
    index = html_dir / "index.html"
    if index.is_file():
        text = index.read_text(encoding="utf-8", errors="replace")
        for old_href, new_href in moves.items():
            label = new_href[len("coverage/") : -len(".html")]
            text = re.sub(
                r"<a href='" + re.escape(old_href) + r"'>[^<]*</a>",
                lambda _m, new_href=new_href, label=label: f"<a href='{new_href}'>{label}</a>",
                text,
            )
        # A row whose source llvm-cov could not read has no page; keep the
        # row (its numbers are valid) but not the dead link.
        text = re.sub(
            r"<a href='coverage/" + re.escape(root_rel) + r"/([^']+)\.html'>[^<]*</a>",
            lambda m: canonical_path(m.group(1), path_map),
            text,
        )
        index.write_text(text, encoding="utf-8")
    return moves


def _canonicalize_summary(text: str, source_root: str, path_map: dict[str, str] | None = None) -> str:
    """Name the files of an llvm-cov text report the way LCOV and HTML do."""
    prefixes = (source_root.rstrip("/") + "/", "/proc/self/cwd/")
    lines = []
    for line in text.splitlines(keepends=True):
        token = line.split(" ", 1)[0]
        name = token
        for prefix in prefixes:
            if name.startswith(prefix):
                name = name[len(prefix) :]
                break
        name = canonical_path(name, path_map) if "/" in token else token
        if name == token:
            lines.append(line)
        else:
            lines.append(name + " " * max(len(token) - len(name), 0) + line[len(token) :])
    return "".join(lines)


def _make_lcov_paths_relative(lcov_content: str, source_root: str, path_map: dict[str, str] | None = None) -> str:
    """Rewrite SF: paths under ``source_root`` (or ``/proc/self/cwd/``) to canonical names.

    The configuration-specific ``bazel-out/<config>/bin/`` prefix of a
    generated header is dropped and a ``_virtual_includes/`` path is mapped to
    its declared header. Other paths are left unchanged.
    """
    prefix = source_root if source_root.endswith("/") else source_root + "/"
    lines = []
    for line in lcov_content.splitlines(keepends=True):
        if line.startswith("SF:"):
            path = line[3:].rstrip("\n")
            for known in (prefix, "/proc/self/cwd/"):
                if path.startswith(known):
                    path = path[len(known) :]
                    break
            lines.append("SF:" + canonical_path(path, path_map) + "\n")
        else:
            lines.append(line)
    return "".join(lines)


_SOURCE_TITLE_RE = re.compile(r"(<div class='source-name-title'><pre>)([^<]*)(</pre></div>)")


def _make_html_paths_relative(html_dir: Path, source_root: str, path_map: dict[str, str] | None = None) -> None:
    """Rewrite absolute source paths in llvm-cov HTML page titles to canonical names.

    Only the source-name-title header text is touched; the page layout is
    handled by :func:`relocate_html_pages`.
    """
    if not html_dir.exists():
        return
    prefix = source_root if source_root.endswith("/") else source_root + "/"

    def _repl(match: "re.Match") -> str:
        title = match.group(2)
        for known in (prefix, "/proc/self/cwd/"):
            if title.startswith(known):
                title = canonical_path(title[len(known) :], path_map)
                break
        return match.group(1) + title + match.group(3)

    for page in html_dir.rglob("*.html"):
        text = page.read_text(encoding="utf-8", errors="replace")
        new_text = _SOURCE_TITLE_RE.sub(_repl, text)
        if new_text != text:
            page.write_text(new_text, encoding="utf-8")


def _filter_lcov(lcov_content: str, target_files: set) -> str:
    """Filter LCOV content to only include records for target files.

    LCOV format: SF:<path> starts a record, end_of_record ends it.
    """
    result = []
    current_record = []
    include = False

    for line in lcov_content.splitlines(keepends=True):
        if line.startswith("SF:"):
            current_record = [line]
            filepath = line[3:].strip()
            # Check if the file path (or its suffix) matches any target file.
            include = any(filepath.endswith(f) for f in target_files)
        elif line.strip() == "end_of_record":
            current_record.append(line)
            if include:
                result.extend(current_record)
            current_record = []
            include = False
        else:
            current_record.append(line)

    return "".join(result)


def get_covered_files(
    llvm_bin_path: Path,
    objects: list[str],
    instr_profile: str | None,
    workspace_root: str,
    path_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """Run a quick llvm-cov report to discover all files with coverage data.

    Returns a dict mapping each raw file path as llvm-cov displays it (after
    stripping the workspace root or ``/proc/self/cwd/``) to its canonical name
    (see :func:`canonical_path`). The raw form is what
    ``--ignore-filename-regex`` must match to suppress one specific compiled
    variant of a file; the canonical form is what the allowlist and the
    test/baseline set arithmetic compare against.
    """
    cmd = [
        str(llvm_bin_path),
        "report",
        f"--path-equivalence=/proc/self/cwd/,{workspace_root}",
    ]
    if instr_profile is None:
        cmd.append("--empty-profile")
    else:
        cmd.extend(["--instr-profile", instr_profile])
    cmd.append(objects[0])
    for obj in objects[1:]:
        cmd.extend(["--object", obj])

    result = run_command(cmd)
    if result.returncode != 0:
        return {}

    files: dict[str, str] = {}
    in_files = False
    for line in result.stdout.splitlines():
        if line.startswith("---"):
            in_files = True
            continue
        if line.startswith("TOTAL"):
            break
        if not in_files:
            continue
        # Extract filename (everything before first multi-space + digit sequence)
        match = re.match(r"^(.+?)\s{2,}\d+", line)
        if match:
            filename = match.group(1).strip()
            # Normalize to workspace-relative form. llvm-cov report prints the
            # raw covmap path: for C++ that is the recorded compilation dir
            # /proc/self/cwd/<rel>, --path-equivalence does not rewrite the
            # DISPLAYED path. Rust covmap paths are already exec-root relative.
            for prefix in (workspace_root.rstrip("/") + "/", "/proc/self/cwd/"):
                if filename.startswith(prefix):
                    filename = filename[len(prefix) :]
                    break
            files[filename] = canonical_path(filename, path_map)

    return files


def prepare_sources(
    r: RunfilesLike,
    args: argparse.Namespace,
    llvm_bin_path: Path,
    sorted_objects: list[str],
    merged_profdata: str,
    baseline_objects: list[str],
    empty_stems: set[str] | None = None,
) -> tuple[FileSelection, dict[str, str], str, list[str]]:
    """Apply the scope, stage the in-scope sources and build the exclusion filters.

    ``empty_stems`` names the sources whose objects carry no coverage mapping
    (see :func:`expand_baseline_archives`).

    Returns the file selection, the path map, the staging root llvm-cov reads
    from, and the ``--ignore-filename-regex`` values.
    """
    workspace_root = args.workspace_root
    path_map = load_path_map(r, args.path_map)
    if path_map:
        print(
            f"INFO: {len(path_map)} headers behind include prefixes are reported under their declared path.",
            file=sys.stderr,
        )

    allowlist_set: set[str] | None = None
    if args.coverage_allowlist:
        allowlist_files = load_coverage_allowlist(r, args.coverage_allowlist)
        if not allowlist_files:
            print("ERROR: Coverage allowlist is empty.", file=sys.stderr)
            sys.exit(-1)
        print(f"INFO: Using coverage allowlist with {len(allowlist_files)} source files.", file=sys.stderr)
        allowlist_set = set(allowlist_files)

    # Files with coverage data: raw covmap path -> canonical name. Test
    # binaries and baseline archives are inspected in SEPARATE llvm-cov runs;
    # combining them in one invocation makes some files vanish (suspected
    # llvm-cov deduplication issue).
    test_covered = get_covered_files(llvm_bin_path, sorted_objects, merged_profdata, workspace_root, path_map)
    print(f"INFO: Test binaries cover {len(set(test_covered.values()))} files.", file=sys.stderr)
    baseline_covered: dict[str, str] = {}
    if baseline_objects:
        baseline_covered = get_covered_files(llvm_bin_path, baseline_objects, None, workspace_root, path_map)
        print(f"INFO: Baseline archives contain {len(set(baseline_covered.values()))} files.", file=sys.stderr)

    selection = select_files(test_covered, baseline_covered, allowlist_set, empty_stems)
    for name, dropped in sorted(selection.duplicates.items()):
        print(
            f"WARNING: {name} is compiled under several paths; reporting one, dropping {sorted(dropped)}",
            file=sys.stderr,
        )
    if selection.baseline_only:
        print(
            f"INFO: {len(selection.baseline_only)} allowlisted files only in baseline "
            f"(e.g., {sorted(selection.baseline_only)[:5]})",
            file=sys.stderr,
        )
    if selection.unmapped:
        print(
            f"WARNING: {len(selection.unmapped)} in-scope files have no coverage data at all (never "
            f"included by a compiled translation unit, or template code that is never instantiated); "
            f"listed in text_report/unmapped_files.txt (e.g., {sorted(selection.unmapped)[:5]})",
            file=sys.stderr,
        )
    if selection.declaration_only or selection.empty_units:
        print(
            f"INFO: {len(selection.declaration_only)} in-scope headers hold declarations only and "
            f"{len(selection.empty_units)} compiled sources hold no code; listed in "
            f"text_report/unmapped_files.txt with their category",
            file=sys.stderr,
        )
    # Stage the in-scope sources under the raw covmap layout so llvm-cov can
    # read every one of them: generated headers (_virtual_includes/) and
    # vendored external headers do not exist below the workspace directory at
    # report time, and the workspace files themselves may not either (fresh
    # CI checkout, remote execution).
    source_root = Path.cwd() / "sources"
    missing = stage_sources(source_root, selection.staged, r, workspace_root)
    if missing:
        print(
            f"WARNING: {len(missing)} in-scope sources were not found; their HTML pages "
            f"will be missing (e.g., {missing[:5]})",
            file=sys.stderr,
        )
    root = str(source_root)
    regexes = [exclusion_regex(raw, [workspace_root, root]) for raw in sorted(selection.excluded)]
    print(f"INFO: Excluding {len(regexes)} compiled files outside the scope.", file=sys.stderr)
    return selection, path_map, root, regexes


def run_llvm_cov_show(
    llvm_bin_path: Path,
    objects: list[str],
    instr_profile: str | None,
    filter_regexes: list[str],
    workspace_root: str,
    output_format: str,
    html_report_dir: Path | None = None,
    cxxfilt: str = "",
) -> subprocess.CompletedProcess:
    """Run llvm-cov show."""
    cmd = [
        str(llvm_bin_path),
        "show",
        f"--format={output_format}",
        f"--path-equivalence=/proc/self/cwd/,{workspace_root}",
        f"--compilation-dir={workspace_root}",
        "--show-branches=count",
        "--show-region-summary=0",
    ]

    if cxxfilt:
        cmd.append(f"--Xdemangler={cxxfilt}")

    for regex in filter_regexes:
        cmd.append(f"--ignore-filename-regex={regex}")

    if html_report_dir:
        cmd.append(f"--output-dir={html_report_dir}")
        cmd.append("--coverage-watermark=100,50")
        cmd.append("--show-expansions")

    if instr_profile is None:
        cmd.append("--empty-profile")
    else:
        cmd.extend(["--instr-profile", instr_profile])
    cmd.append(objects[0])
    for obj in objects[1:]:
        cmd.extend(["--object", obj])

    return run_command(cmd)


def run_llvm_cov_export(
    llvm_bin_path: Path,
    objects: list[str],
    instr_profile: str | None,
    filter_regexes: list[str],
    workspace_root: str,
) -> subprocess.CompletedProcess:
    """Run llvm-cov export to produce LCOV format."""
    cmd = [
        str(llvm_bin_path),
        "export",
        "--format=lcov",
        f"--path-equivalence=/proc/self/cwd/,{workspace_root}",
        f"--compilation-dir={workspace_root}",
    ]

    for regex in filter_regexes:
        cmd.append(f"--ignore-filename-regex={regex}")

    if instr_profile is None:
        cmd.append("--empty-profile")
    else:
        cmd.extend(["--instr-profile", instr_profile])
    cmd.append(objects[0])
    for obj in objects[1:]:
        cmd.extend(["--object", obj])

    # Keep stderr separate: llvm-cov warnings must not end up in the LCOV data.
    return run_command(cmd, separate_stderr=True)


def run_llvm_cov_report(
    llvm_bin_path: Path,
    objects: list[str],
    instr_profile: str | None,
    filter_regexes: list[str],
    workspace_root: str,
) -> subprocess.CompletedProcess:
    """Run llvm-cov report for a text summary."""
    cmd = [
        str(llvm_bin_path),
        "report",
        f"--path-equivalence=/proc/self/cwd/,{workspace_root}",
        "--show-region-summary=0",
        "--show-branch-summary=1",
    ]

    for regex in filter_regexes:
        cmd.append(f"--ignore-filename-regex={regex}")

    if instr_profile is None:
        cmd.append("--empty-profile")
    else:
        cmd.extend(["--instr-profile", instr_profile])
    cmd.append(objects[0])
    for obj in objects[1:]:
        cmd.extend(["--object", obj])

    return run_command(cmd)


def extract_reports(reports: list[str]) -> tuple[set[str], set[str]]:
    """Extract profdata and object files from per-test zip files."""
    valid_profdata_files = set()
    valid_object_files = set()

    for i, report_path in enumerate(reports):
        # Skip baseline_coverage files (LCOV format, not our zip).
        if "baseline_coverage" in report_path:
            continue

        report = Path(report_path)
        if not report.exists() or report.stat().st_size == 0:
            continue

        # Check if it's a valid zip.
        if not zipfile.is_zipfile(report):
            continue

        profdata_name = f"coverage_report_{i:08d}.profdata"

        try:
            with zipfile.ZipFile(report, "r") as archive:
                # Extract meta.
                meta_json = archive.read("meta/meta.json")
                target_meta = json.loads(meta_json)

                # Extract profdata.
                profdata_content = archive.read("profdata/target.profdata")
                profdata_path = Path.cwd() / profdata_name
                with open(profdata_path, "wb") as f:
                    f.write(profdata_content)

                valid_profdata_files.add(str(profdata_path))

                # Collect object files.
                for obj in target_meta.get("object_files", []):
                    if obj and Path(obj).exists():
                        valid_object_files.add(os.path.realpath(obj))

        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
            print(f"WARNING: Skipping invalid report {report_path}: {e}", file=sys.stderr)
            continue

    return valid_profdata_files, valid_object_files


def read_reports_file(reports_file: Path) -> list[str]:
    """Read the reports file listing all per-test coverage outputs."""
    with open(reports_file, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _read_ar_members(path: str) -> list[tuple]:
    """Parse a Unix ar archive, returning (name, data_offset, size) tuples.

    Handles the GNU long-name table ("//" member with "/<offset>" references).
    Returns an empty list when the file is not an ar archive.
    """
    members = []
    longnames = b""
    with open(path, "rb") as f:
        if f.read(8) != b"!<arch>\n":
            return []
        while True:
            header = f.read(60)
            if len(header) < 60:
                break
            name = header[0:16].decode(errors="replace").rstrip()
            try:
                size = int(header[48:58].decode().strip() or "0")
            except ValueError:
                break
            data_offset = f.tell()
            if name == "//":
                longnames = f.read(size)
            else:
                if name.startswith("/") and name[1:].isdigit():
                    start = int(name[1:])
                    end = longnames.find(b"\n", start)
                    name = longnames[start:end].decode(errors="replace").rstrip("/")
                elif name.endswith("/"):
                    name = name[:-1]
                members.append((name, data_offset, size))
                f.seek(size, 1)
            if size % 2 == 1:
                f.seek(1, 1)
    return members


_ELF_MAGIC = b"\x7fELF"


def object_has_covmap(data: bytes) -> bool:
    """True when ``data`` is an ELF64 object with a ``__llvm_covmap`` section.

    Only the ELF header, the section header table and the section name table
    are inspected. Anything that is not an ELF64 object (an rlib's lib.rmeta,
    a text member) has no coverage mapping by definition.
    """
    if len(data) < 64 or data[:4] != _ELF_MAGIC or data[4] != 2:  # not ELF, or not ELFCLASS64
        return False
    order = "little" if data[5] == 1 else "big"
    shoff = int.from_bytes(data[0x28:0x30], order)
    shentsize = int.from_bytes(data[0x3A:0x3C], order)
    shnum = int.from_bytes(data[0x3C:0x3E], order)
    shstrndx = int.from_bytes(data[0x3E:0x40], order)
    if shoff == 0 or shentsize < 64 or shstrndx >= shnum:
        return False

    def section(index: int) -> tuple[int, int, int] | None:
        base = shoff + index * shentsize
        header = data[base : base + 64]
        if len(header) < 64:
            return None
        return (
            int.from_bytes(header[0:4], order),  # sh_name
            int.from_bytes(header[0x18:0x20], order),  # sh_offset
            int.from_bytes(header[0x20:0x28], order),  # sh_size
        )

    strtab = section(shstrndx)
    if strtab is None:
        return False
    names = data[strtab[1] : strtab[1] + strtab[2]]
    for index in range(shnum):
        entry = section(index)
        if entry is None:
            continue
        end = names.find(b"\x00", entry[0])
        if end != -1 and names[entry[0] : end] == b"__llvm_covmap":
            return True
    return False


def expand_baseline_archives(manifest: dict[str, str], workdir: Path) -> tuple[list[str], set[str]]:
    """Give llvm-cov only the baseline archive members that carry a coverage mapping.

    llvm-cov rejects an archive as a whole ("no coverage data found") as soon
    as one member has no ``__llvm_covmap`` section: the ``lib.rmeta`` member
    of a Rust rlib (exposed as a .a symlink by rules_rust), or the object of
    an empty translation unit such as the placeholder .cpp of a header-only
    C++ library. Every other file of that library would then lose its 0 %
    baseline. Such an archive is replaced by its members that do carry a
    mapping, extracted into ``workdir``; archives whose members all carry one
    and non-archive objects (executables) pass through unchanged.

    ``manifest`` maps absolute paths to short paths (see
    :func:`load_baseline_manifest`). Returns the object list for llvm-cov and
    the ``<dir>/<name>`` stems of the dropped object members, which identify
    the sources compiled without code.
    """
    result: list[str] = []
    empty_stems: set[str] = set()
    extracted = archives_split = 0
    for path in sorted(manifest):
        members = _read_ar_members(path) if path.endswith((".a", ".rlib")) else []
        if not members:
            result.append(path)
            continue
        with open(path, "rb") as f:
            usable = []
            for name, offset, size in members:
                f.seek(offset)
                if object_has_covmap(f.read(size)):
                    usable.append((name, offset, size))
                elif name.endswith(".o") and not name.endswith(".rcgu.o"):
                    empty_stems.add(os.path.join(os.path.dirname(manifest[path]), _stem(name)))
            if len(usable) == len(members):
                result.append(path)
                continue
            archives_split += 1
            workdir.mkdir(parents=True, exist_ok=True)
            for index, (_name, offset, size) in enumerate(usable):
                f.seek(offset)
                out_path = workdir / f"{Path(path).stem}.{index}.o"
                out_path.write_bytes(f.read(size))
                result.append(str(out_path))
                extracted += 1
    if archives_split:
        print(
            f"INFO: {archives_split} baseline archive(s) had members without a coverage mapping; "
            f"passing their {extracted} usable object(s) to llvm-cov individually.",
            file=sys.stderr,
        )
    return result, empty_stems


def expand_rlib_archives(objects: list[str], workdir: Path) -> list[str]:
    """Backwards-compatible wrapper of :func:`expand_baseline_archives` for a plain path list."""
    return expand_baseline_archives({path: os.path.basename(path) for path in objects}, workdir)[0]


def resolve_tool(
    runfiles: RunfilesLike | None,
    flag_value: str | None,
    fallback_rlocation: str,
) -> Path | None:
    """Resolve an llvm tool path.

    Preference order: the explicit rlocation path passed by the
    reporter_wrapper (consumer-supplied toolchain label), then the legacy
    "llvm_toolchain/..." runfiles location, then the raw value as a plain path.
    """
    for candidate in (flag_value, fallback_rlocation):
        if not candidate:
            continue
        if runfiles:
            location = runfiles.Rlocation(candidate)
            if location and Path(location).exists():
                return Path(location)
        if Path(candidate).exists():
            return Path(candidate)
    return None


def find_cxxfilt(
    llvm_bin_path: Path,
    runfiles: RunfilesLike | None = None,
    explicit: str | None = None,
) -> str:
    """Locate llvm-cxxfilt for demangling (C++ Itanium and Rust v0/legacy symbols).

    Tries the explicit rlocation path from the reporter_wrapper first, then the
    directory of llvm-cov, then the @llvm_toolchain_llvm distribution via
    runfiles (toolchains_llvm declares no alias for llvm-cxxfilt).
    Returns an empty string when unavailable (demangling is cosmetic).
    """
    if explicit:
        resolved = resolve_tool(runfiles, explicit, "")
        if resolved:
            return str(resolved)
    sibling = llvm_bin_path.parent / "llvm-cxxfilt"
    if sibling.exists():
        return str(sibling)
    r = runfiles or Runfiles.Create()
    if r:
        location = r.Rlocation("llvm_toolchain_llvm/bin/llvm-cxxfilt")
        if location and Path(location).exists():
            return location
    return ""


def load_coverage_allowlist(runfiles: RunfilesLike, rlocation_path: str) -> list[str]:
    """Load coverage allowlist (package paths) from a file via Bazel runfiles."""
    path = runfiles.Rlocation(rlocation_path)
    if not path or not Path(path).exists():
        return []

    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def load_path_map(runfiles: RunfilesLike, rlocation_path: str | None) -> dict[str, str]:
    """Load the scope's ``<virtual path>\\t<canonical path>`` map; empty when absent."""
    if not rlocation_path:
        return {}
    path = runfiles.Rlocation(rlocation_path)
    if not path or not Path(path).exists():
        print(f"WARNING: Path map not found: {rlocation_path}", file=sys.stderr)
        return {}
    mapping: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        virtual, _, canonical = line.partition("\t")
        if virtual and canonical:
            mapping[virtual] = canonical
    return mapping


def load_baseline_manifest(runfiles: RunfilesLike, rlocation_path: str | None) -> dict[str, str]:
    """{absolute path: short path} of the baseline objects listed in the scope's manifest.

    The manifest lists short_paths of files built by the CONSUMER repository,
    which is always the root module ("_main") in a coverage run. A listed
    object that cannot be found is a hard error: a silently missing archive
    would hide every untested file of that library.
    """
    if not rlocation_path:
        return {}
    path = runfiles.Rlocation(rlocation_path)
    if not path or not Path(path).exists():
        print(f"WARNING: Baseline objects manifest not found: {rlocation_path}", file=sys.stderr)
        return {}
    resolved: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        short_path = line.strip()
        if not short_path or short_path.startswith("#"):
            continue
        # Do NOT use runfiles.CurrentRepository() here: this script lives in
        # score_coverage, so that would resolve against the wrong repo.
        location = runfiles.Rlocation(os.path.join("_main", short_path))
        if location and os.path.exists(location):
            resolved[location] = short_path
        else:
            print(f"ERROR: Baseline object not found: {short_path}", file=sys.stderr)
            sys.exit(-1)
    return resolved


def load_baseline_objects(runfiles: RunfilesLike, rlocation_path: str | None) -> list[str]:
    """Absolute paths of the baseline objects, sorted (see :func:`load_baseline_manifest`)."""
    return sorted(load_baseline_manifest(runfiles, rlocation_path))


def run_command(cmd: list[str], separate_stderr: bool = False) -> subprocess.CompletedProcess:
    """Run a command and exit on failure.

    With separate_stderr the child's stderr is captured separately and
    forwarded to our stderr — required when stdout is machine-consumed data
    (LCOV) that llvm-cov warnings must not corrupt.
    """
    try:
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if separate_stderr else subprocess.STDOUT,
            text=True,
        )
        if separate_stderr and result.stderr:
            print(result.stderr, file=sys.stderr)
        return result
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Command failed with code {e.returncode}:", file=sys.stderr)
        print(f"  {' '.join(cmd[:10])}{'...' if len(cmd) > 10 else ''}", file=sys.stderr)
        if e.stdout:
            print(e.stdout, file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        sys.exit(1)


def write_empty_output(output_file: Path) -> None:
    """Write an empty (but valid) zip so Bazel's coverage action still succeeds.

    Matches Bazel's own behaviour for runs that produce no coverage data
    (e.g. a coverage invocation whose tests were all filtered out).
    """
    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED):
        pass


def create_zip(root: Path, directories: list[Path], output_file: Path) -> None:
    """Create a zip file from the given directories relative to root."""
    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for directory in directories:
            if not directory.exists():
                continue
            for dirpath, _, files in os.walk(directory):
                for filename in files:
                    file_path = Path(dirpath) / filename
                    arcname = file_path.relative_to(root)
                    zf.write(file_path, arcname)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments matching the Bazel coverage_report_generator interface."""
    parser = argparse.ArgumentParser(description="LLVM coverage reporter for Bazel")
    parser.add_argument("--output_file", type=Path, required=True)
    parser.add_argument("--reports_file", type=Path, required=True)
    parser.add_argument(
        "--coverage_allowlist",
        type=str,
        default=None,
        help="Rlocation path to the coverage allowlist file (preferred over filter_regexes)",
    )
    parser.add_argument(
        "--path_map",
        type=str,
        default=None,
        help="Rlocation path to the scope's virtual-includes -> declared header map",
    )
    parser.add_argument(
        "--baseline_objects",
        type=str,
        default=None,
        help="Rlocation path to the baseline objects manifest (archive .a files)",
    )
    parser.add_argument(
        "--workspace_root", type=str, required=True, help="Real workspace root path for source path mapping"
    )
    parser.add_argument(
        "--llvm_cov", type=str, default=None, help="Rlocation path to llvm-cov (supplied by score_coverage_reporter)"
    )
    parser.add_argument(
        "--llvm_profdata",
        type=str,
        default=None,
        help="Rlocation path to llvm-profdata (supplied by score_coverage_reporter)",
    )
    parser.add_argument(
        "--llvm_cxxfilt",
        type=str,
        default=None,
        help="Rlocation path to llvm-cxxfilt (supplied by score_coverage_reporter)",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    main()
