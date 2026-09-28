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
"""Final coverage report generator for gcov-based toolchains (GCC, QNX QCC).

Bazel's own per-test collector runs ``gcov`` over the ``.gcda`` counters a test
wrote (on QNX the counters travel back from the QEMU guest through
``score_qnx_unit_tests``) and stores one LCOV file per test. This script is
the ``--coverage_report_generator`` that follows: it merges the per-test LCOV
files, restricts them to the coverage scope, adds a zero-coverage baseline for
in-scope translation units no test executed (``gcov`` over their ``.gcno``
notes without counters), and writes the same report zip as the LLVM reporter:
``html_report/`` (rendered by gcovr), ``lcov_report/lcov.dat`` and
``text_report/`` (summary and ``unmapped_files.txt``).

Expected Bazel interface:
    --reports_file=<path>    Text file listing paths to all per-test coverage outputs
    --output_file=<path>     Where to write the final report (zip)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from python.runfiles import Runfiles

from score_coverage.reporter import (
    FileSelection,
    RunfilesLike,
    canonical_path,
    create_zip,
    format_unmapped_files,
    load_coverage_allowlist,
    load_path_map,
    read_reports_file,
    resolve_foreign_virtual_includes,
    resolve_tool,
    select_files,
    stage_sources,
    write_empty_output,
)

# Sources the gcov backend can never carry data for: rustc is an LLVM
# compiler and emits no .gcda counters.
UNMAPPED_NOT_INSTRUMENTED = "not-instrumented"
_RUST_SUFFIXES = (".rs",)


@dataclass
class FileRecord:
    """Coverage of one source file: line hits, branch hits and functions."""

    lines: dict[int, int] = field(default_factory=dict)
    """line number -> execution count."""
    branches: dict[tuple[int, str, str], int | None] = field(default_factory=dict)
    """(line, block, branch) -> taken count, or None when the block was never reached ('-')."""
    functions: dict[str, tuple[int, int]] = field(default_factory=dict)
    """function name -> (start line, execution count)."""

    def add(self, other: "FileRecord") -> None:
        """Accumulate another record of the same file (another test's run): counts add up."""
        for line, count in other.lines.items():
            self.lines[line] = self.lines.get(line, 0) + count
        for key, count in other.branches.items():
            current = self.branches.get(key)
            if count is None:
                self.branches.setdefault(key, None)
            else:
                self.branches[key] = (current or 0) + count
        for name, (line, count) in other.functions.items():
            _, current = self.functions.get(name, (line, 0))
            self.functions[name] = (line, current + count)

    def zeroed(self) -> "FileRecord":
        """The same structure with every count at zero (a baseline entry)."""
        return FileRecord(
            lines=dict.fromkeys(self.lines, 0),
            branches={key: (None if count is None else 0) for key, count in self.branches.items()},
            functions={name: (line, 0) for name, (line, _) in self.functions.items()},
        )


def main(argv: list[str] | None = None) -> None:
    """Main entry point. ``argv`` defaults to ``sys.argv[1:]``."""
    args = parse_args(argv)
    r = Runfiles.Create()
    if r is None:
        print("ERROR: runfiles are unavailable; the reporter must run as a Bazel coverage action.", file=sys.stderr)
        sys.exit(1)

    reports = [path for path in read_reports_file(args.reports_file) if not path.endswith("baseline_coverage.dat")]
    if not reports:
        print("INFO: No coverage reports listed; writing empty output.", file=sys.stderr)
        write_empty_output(args.output_file)
        return

    gcov_path = resolve_tool(r, args.gcov, "gcov")
    if not gcov_path:
        print(
            "ERROR: gcov not found in runfiles. Pass --gcov (the score_coverage_reporter macro does this).",
            file=sys.stderr,
        )
        sys.exit(1)

    workspace_root = args.workspace_root
    path_map = load_path_map(r, args.path_map)
    allowlist_files = load_coverage_allowlist(r, args.coverage_allowlist) if args.coverage_allowlist else []
    if args.coverage_allowlist and not allowlist_files:
        print("ERROR: Coverage allowlist is empty.", file=sys.stderr)
        sys.exit(-1)
    allowlist: set[str] | None = set(allowlist_files) if allowlist_files else None
    if allowlist is not None:
        print(f"INFO: Using coverage allowlist with {len(allowlist)} source files.", file=sys.stderr)

    # Per-test LCOV files from Bazel's collector, summed per file.
    tested: dict[str, FileRecord] = {}
    for report in reports:
        for raw, record in parse_lcov(Path(report).read_text(encoding="utf-8", errors="replace")).items():
            tested.setdefault(normalize_raw(raw, workspace_root), FileRecord()).add(record)
    print(f"INFO: {len(reports)} per-test reports cover {len(tested)} files.", file=sys.stderr)

    # Zero-coverage baseline from the .gcno notes of every in-scope translation unit.
    gcno_files = load_gcno_manifest(r, args.gcno_manifest)
    baseline: dict[str, FileRecord] = {}
    for gcno in sorted(gcno_files):
        for raw, record in gcov_baseline(gcov_path, gcno).items():
            baseline.setdefault(normalize_raw(raw, workspace_root), FileRecord()).add(record)
    print(f"INFO: {len(gcno_files)} gcno files describe {len(baseline)} files.", file=sys.stderr)

    canonical = canonical_names(set(tested) | set(baseline), path_map, allowlist)
    test_covered = {raw: canonical[raw] for raw in tested}
    baseline_covered = {raw: canonical[raw] for raw in baseline}
    compiled_stems = compiled_stems_from_gcno(list(gcno_files.values()))
    selection = select_files(test_covered, baseline_covered, allowlist, compiled_stems)
    not_instrumented = mark_not_instrumented(selection)
    report_selection(selection, not_instrumented)

    merged = merge_records(tested, baseline, selection)

    # Stage the in-scope sources so gcovr can render them (generated headers
    # and external repositories are not reachable through the workspace).
    source_root = Path.cwd() / "sources"
    missing = stage_sources(source_root, {name: name for name in merged}, r, workspace_root)
    if missing:
        print(f"WARNING: {len(missing)} in-scope sources were not found (e.g., {missing[:5]})", file=sys.stderr)

    lcov_report_dir = Path.cwd() / "lcov_report"
    lcov_report_dir.mkdir(exist_ok=True)
    (lcov_report_dir / "lcov.dat").write_text(render_lcov(merged), encoding="utf-8")

    html_report_dir = Path.cwd() / "html_report"
    text_report_dir = Path.cwd() / "text_report"
    html_report_dir.mkdir(exist_ok=True)
    text_report_dir.mkdir(exist_ok=True)
    render_html(merged, source_root, html_report_dir, text_report_dir / "summary.txt")
    print((text_report_dir / "summary.txt").read_text(encoding="utf-8"), file=sys.stderr)
    (text_report_dir / "unmapped_files.txt").write_text(
        format_unmapped_files(selection)
        + "".join(f"{UNMAPPED_NOT_INSTRUMENTED}\t{n}\n" for n in sorted(not_instrumented)),
        encoding="utf-8",
    )

    create_zip(
        root=Path.cwd(), directories=[html_report_dir, lcov_report_dir, text_report_dir], output_file=args.output_file
    )
    print(f"INFO: gcov coverage reporter completed. Output: {args.output_file}", file=sys.stderr)


# -----------------------------------------------------------------------------
# LCOV parsing and rendering
# -----------------------------------------------------------------------------


def parse_lcov(content: str) -> dict[str, FileRecord]:
    """Parse LCOV text into ``{SF path: FileRecord}``; records of the same file are summed."""
    records: dict[str, FileRecord] = {}
    current: FileRecord | None = None
    name = ""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("SF:"):
            name, current = line[3:], FileRecord()
        elif current is None:
            continue
        elif line.startswith("DA:"):
            parts = line[3:].split(",")
            current.lines[int(parts[0])] = current.lines.get(int(parts[0]), 0) + max(0, int(parts[1]))
        elif line.startswith("BRDA:"):
            ln, block, branch, taken = line[5:].split(",", 3)
            key = (int(ln), block, branch)
            count = None if taken == "-" else max(0, int(taken))
            if count is None:
                current.branches.setdefault(key, None)
            else:
                current.branches[key] = (current.branches.get(key) or 0) + count
        elif line.startswith("FN:"):
            start, fname = line[3:].split(",", 1)
            _, count = current.functions.get(fname, (0, 0))
            current.functions[fname] = (int(start), count)
        elif line.startswith("FNDA:"):
            hits, fname = line[5:].split(",", 1)
            start, count = current.functions.get(fname, (0, 0))
            current.functions[fname] = (start, count + int(hits))
        elif line == "end_of_record":
            records.setdefault(name, FileRecord()).add(current)
            current = None
    return records


def render_lcov(records: dict[str, FileRecord]) -> str:
    """LCOV text for the records, one ``SF:`` block per file in sorted order."""
    out: list[str] = []
    for name in sorted(records):
        rec = records[name]
        out.append(f"SF:{name}")
        for fname, (start, _) in sorted(rec.functions.items(), key=lambda item: (item[1][0], item[0])):
            out.append(f"FN:{start},{fname}")
        for fname, (_, count) in sorted(rec.functions.items(), key=lambda item: (item[1][0], item[0])):
            out.append(f"FNDA:{count},{fname}")
        if rec.functions:
            out.append(f"FNF:{len(rec.functions)}")
            out.append(f"FNH:{sum(1 for _, count in rec.functions.values() if count > 0)}")
        for line in sorted(rec.lines):
            out.append(f"DA:{line},{rec.lines[line]}")
        for (line, block, branch), count in sorted(
            rec.branches.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])
        ):
            out.append(f"BRDA:{line},{block},{branch},{'-' if count is None else count}")
        if rec.branches:
            out.append(f"BRF:{len(rec.branches)}")
            out.append(f"BRH:{sum(1 for count in rec.branches.values() if count)}")
        out.append(f"LF:{len(rec.lines)}")
        out.append(f"LH:{sum(1 for count in rec.lines.values() if count > 0)}")
        out.append("end_of_record")
    return "".join(line + "\n" for line in out)


# -----------------------------------------------------------------------------
# Paths and selection
# -----------------------------------------------------------------------------


def normalize_raw(path: str, workspace_root: str) -> str:
    """Strip the workspace root, ``/proc/self/cwd/`` and ``./`` so paths are exec-root relative."""
    for prefix in (workspace_root.rstrip("/") + "/", "/proc/self/cwd/", "./"):
        if path.startswith(prefix):
            return path[len(prefix) :]
    return path


def canonical_names(raws: set[str], path_map: dict[str, str], allowlist: set[str] | None) -> dict[str, str]:
    """raw exec-root-relative path -> canonical name (config prefix dropped, virtual includes resolved)."""
    names = {raw: canonical_path(raw, path_map) for raw in raws}
    if allowlist is not None:
        foreign, ambiguous = resolve_foreign_virtual_includes(set(names.values()), allowlist)
        for raw, name in names.items():
            if name in foreign:
                names[raw] = foreign[name]
        for name, candidates in sorted(ambiguous.items()):
            print(
                f"WARNING: {name} matches several in-scope files ({candidates}); it stays out of the report.",
                file=sys.stderr,
            )
    return names


def mark_not_instrumented(selection: FileSelection) -> set[str]:
    """Move allowlisted Rust sources out of the findings: gcov cannot instrument them."""
    rust = {name for name in selection.unmapped if name.endswith(_RUST_SUFFIXES)}
    selection.unmapped -= rust
    return rust


def report_selection(selection: FileSelection, not_instrumented: set[str]) -> None:
    """Log what the scope did to the collected files."""
    if selection.baseline_only:
        print(f"INFO: {len(selection.baseline_only)} allowlisted files only in baseline.", file=sys.stderr)
    if selection.excluded:
        print(f"INFO: Excluding {len(selection.excluded)} compiled files outside the scope.", file=sys.stderr)
    if selection.unmapped:
        print(
            f"WARNING: {len(selection.unmapped)} in-scope files have no coverage data at all; "
            f"listed in text_report/unmapped_files.txt (e.g., {sorted(selection.unmapped)[:5]})",
            file=sys.stderr,
        )
    if not_instrumented:
        print(
            f"INFO: {len(not_instrumented)} Rust sources are in scope but the gcov backend cannot instrument them.",
            file=sys.stderr,
        )


def merge_records(
    tested: dict[str, FileRecord], baseline: dict[str, FileRecord], selection: FileSelection
) -> dict[str, FileRecord]:
    """Canonical name -> record: tested data where it exists, zeroed baseline data otherwise."""
    merged: dict[str, FileRecord] = {}
    for raw, name in selection.staged.items():
        if raw in tested:
            merged.setdefault(name, FileRecord()).add(tested[raw])
    for raw, name in selection.staged.items():
        if raw in baseline and name not in merged:
            merged.setdefault(name, FileRecord()).add(baseline[raw].zeroed())
    return merged


# -----------------------------------------------------------------------------
# gcov baseline
# -----------------------------------------------------------------------------


def load_gcno_manifest(runfiles: RunfilesLike, rlocation_path: str | None) -> dict[str, str]:
    """``{absolute path: short path}`` of the .gcno files listed by the scope; a missing file is an error."""
    if not rlocation_path:
        return {}
    manifest = runfiles.Rlocation(rlocation_path)
    if not manifest or not Path(manifest).exists():
        print(f"WARNING: gcno manifest not found: {rlocation_path}", file=sys.stderr)
        return {}
    resolved: dict[str, str] = {}
    for line in Path(manifest).read_text(encoding="utf-8").splitlines():
        short_path = line.strip()
        if not short_path or short_path.startswith("#"):
            continue
        location = runfiles.Rlocation(os.path.join("_main", short_path))
        if not location or not os.path.exists(location):
            print(f"ERROR: gcno file not found: {short_path}", file=sys.stderr)
            sys.exit(-1)
        resolved[location] = short_path
    return resolved


_GCNO_RE = re.compile(r"(?:^|/)(?P<pkg>.*?)/?_objs/[^/]+/(?P<src>.+?)(?:\.pic)?\.gcno$")


def compiled_stems_from_gcno(gcno_files: list[str]) -> set[str]:
    """``<pkg>/<source stem>`` of every translation unit that has a .gcno: the sources that were compiled.

    The short path ``src/_objs/uncovered/empty_unit.pic.gcno`` names
    ``src/empty_unit``. A placeholder source that contains no code has a
    .gcno like any other and is thereby classified as compiled without code
    instead of as a finding.
    """
    stems: set[str] = set()
    for gcno in gcno_files:
        match = _GCNO_RE.search(gcno)
        if match:
            stems.add(f"{match.group('pkg')}/{match.group('src')}" if match.group("pkg") else match.group("src"))
    return stems


def gcov_baseline(gcov_path: Path, gcno: str) -> dict[str, FileRecord]:
    """Run gcov over one .gcno without counters; every line and branch comes back at zero.

    Returns ``{gcov file path: FileRecord}``: the translation unit and every
    header it instantiated code from, paths as gcov records them (relative
    to the compilation directory, i.e. exec-root relative under Bazel).
    """
    result = subprocess.run(
        [str(gcov_path), "--json-format", "--stdout", "--branch-probabilities", gcno],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"WARNING: gcov failed on {gcno}: {result.stderr.strip()[:200]}", file=sys.stderr)
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"WARNING: gcov produced no JSON for {gcno}: {e}", file=sys.stderr)
        return {}
    return records_from_gcov_json(data)


def records_from_gcov_json(data: dict) -> dict[str, FileRecord]:
    """Convert gcov's JSON intermediate format into records (counts as reported)."""
    records: dict[str, FileRecord] = {}
    for entry in data.get("files", []):
        rec = FileRecord()
        blocks: dict[int, int] = defaultdict(int)
        for line in entry.get("lines", []):
            number = int(line["line_number"])
            rec.lines[number] = rec.lines.get(number, 0) + int(line.get("count", 0))
            for branch in line.get("branches", []):
                index = blocks[number]
                blocks[number] += 1
                rec.branches[(number, "0", str(index))] = int(branch.get("count", 0))
        for function in entry.get("functions", []):
            rec.functions[function["name"]] = (
                int(function.get("start_line", 0)),
                int(function.get("execution_count", 0)),
            )
        records[entry["file"]] = rec
    return records


# -----------------------------------------------------------------------------
# HTML through gcovr
# -----------------------------------------------------------------------------


def gcovr_tracefile(records: dict[str, FileRecord]) -> dict:
    """The records as a gcovr JSON tracefile (format 0.14)."""
    files = []
    for name in sorted(records):
        rec = records[name]
        by_line: dict[int, list[dict]] = defaultdict(list)
        for (line, block, branch), count in sorted(rec.branches.items()):
            # gcovr's source page prints "block -> block" for every branch and
            # needs both ids; LCOV's block and branch numbers stand in for them.
            by_line[line].append(
                {
                    "count": count or 0,
                    "fallthrough": False,
                    "throw": False,
                    "source_block_id": int(block) if block.isdigit() else 0,
                    "destination_block_id": int(branch) if branch.isdigit() else 0,
                }
            )
        files.append(
            {
                "file": name,
                "lines": [
                    {"line_number": line, "count": rec.lines[line], "branches": by_line.get(line, [])}
                    for line in sorted(rec.lines)
                ],
                "functions": [
                    {"name": fname, "lineno": start, "execution_count": count}
                    for fname, (start, count) in sorted(rec.functions.items(), key=lambda item: (item[1][0], item[0]))
                    if start > 0
                ],
            }
        )
    return {"gcovr/format_version": "0.14", "files": files}


def render_html(records: dict[str, FileRecord], source_root: Path, html_dir: Path, summary: Path) -> None:
    """Render the HTML report (index.html plus one page per file) and the text summary with gcovr."""
    tracefile = Path.cwd() / "gcovr_tracefile.json"
    tracefile.write_text(json.dumps(gcovr_tracefile(records)), encoding="utf-8")
    argv = [
        "gcovr",
        "--json-add-tracefile",
        str(tracefile),
        "--root",
        str(source_root),
        "--html-details",
        str(html_dir / "index.html"),
        "--txt",
        str(summary),
    ]
    from gcovr.__main__ import main as gcovr_main  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    saved_argv = sys.argv
    sys.argv = argv
    try:
        gcovr_main()
    except SystemExit as e:
        if e.code not in (0, None):
            print(f"ERROR: gcovr exited with code {e.code}", file=sys.stderr)
            sys.exit(1)
    finally:
        sys.argv = saved_argv


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments matching the Bazel coverage_report_generator interface."""
    parser = argparse.ArgumentParser(description="gcov coverage reporter for Bazel")
    parser.add_argument("--output_file", type=Path, required=True)
    parser.add_argument("--reports_file", type=Path, required=True)
    parser.add_argument("--coverage_allowlist", type=str, default=None, help="Rlocation path to the allowlist")
    parser.add_argument("--path_map", type=str, default=None, help="Rlocation path to the virtual-includes map")
    parser.add_argument("--gcno_manifest", type=str, default=None, help="Rlocation path to the gcno manifest")
    parser.add_argument("--workspace_root", type=str, required=True, help="Real workspace root path")
    parser.add_argument("--gcov", type=str, default=None, help="Rlocation path to the toolchain's gcov binary")
    return parser.parse_args(argv)


if __name__ == "__main__":
    main()
