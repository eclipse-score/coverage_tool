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
"""Select and name the source files included in a coverage report.

Both coverage backends use these helpers to map compiler-recorded paths to
source paths, apply the consumer's scope, and describe files with no data.
"""

import os
import re
import sys
from dataclasses import dataclass, field

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


_FOREIGN_VIRTUAL_RE = re.compile(r"^(.*/)?_virtual_includes/[^/]+/(?P<tail>.+)$")


def resolve_foreign_virtual_includes(
    names: set[str], allowlist: set[str]
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Map ``_virtual_includes/`` paths of targets outside the scope to the allowlisted file.

    The scope's path map only covers virtual-include trees of targets the
    aspect visited. A test-only twin of a library (same ``hdrs`` behind
    ``strip_include_prefix``, other copts; baselibs' ``futurecpp_internal``)
    generates its own tree from the very same files, and test binaries record
    that tree. Such a name is resolved by its tail: the allowlisted file that
    ends with ``<tail>`` at a path-component boundary. If no file matches the
    full tail (an ``include_prefix`` added components), shorter tails are
    tried. Returns ``{virtual name: canonical}`` and ``{virtual name: candidates}``
    for tails that match several allowlisted files (left unresolved).
    """
    resolved: dict[str, str] = {}
    ambiguous: dict[str, list[str]] = {}
    for name in sorted(names):
        match = _FOREIGN_VIRTUAL_RE.match(name)
        if not match or name in allowlist:
            continue
        parts = match.group("tail").split("/")
        for start in range(len(parts)):
            suffix = "/".join(parts[start:])
            candidates = sorted(a for a in allowlist if a == suffix or a.endswith("/" + suffix))
            if len(candidates) == 1:
                resolved[name] = candidates[0]
                break
            if len(candidates) > 1:
                ambiguous[name] = candidates
                break
    return resolved, ambiguous


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
    """unmapped sources that were compiled into a baseline archive: no code of their own."""


_HEADER_SUFFIXES = (".h", ".hpp", ".hh", ".hxx", ".inl", ".ipp", ".tpp")


def _is_header(path: str) -> bool:
    return path.endswith(_HEADER_SUFFIXES)


def source_stem(path: str) -> str:
    """Path without its last extension: ``src/foo.h`` and ``src/foo.cpp`` share ``src/foo``."""
    return os.path.splitext(path)[0]


def select_files(
    test_covered: dict[str, str],
    baseline_covered: dict[str, str],
    allowlist: set[str] | None,
    compiled_stems: set[str] | None = None,
) -> FileSelection:
    """Apply the scope allowlist to the raw files of test binaries and baseline archives.

    ``allowlist`` is a set of canonical names; ``None`` keeps every file.
    ``compiled_stems`` are ``<dir>/<name>`` stems of the baseline archives'
    object members (see :func:`expand_baseline_archives`); an allowlisted
    source with such a stem but no coverage data was compiled and holds no
    code of its own.
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
        stems_with_data = {source_stem(name) for name in with_data}
        declaration_only = {name for name in unmapped if _is_header(name) and source_stem(name) in stems_with_data}
        unmapped -= declaration_only
        # A source whose object sits in a baseline archive but that has no
        # coverage data of its own is a placeholder translation unit of a
        # header-only library: compiled, nothing to cover in that file.
        if compiled_stems:
            empty_units = {name for name in unmapped if not _is_header(name) and source_stem(name) in compiled_stems}
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


_TEST_SUBDIRECTORIES = ("test", "tests")


def instrumentation_filter_suspects(no_data: set[str], with_data: set[str]) -> list[str]:
    """In-scope files without test data whose directory is tested from a ``test``/``tests`` subdirectory.

    Bazel guesses ``--instrumentation_filter`` from the packages of the test
    targets and strips only a trailing ``/tests``. A library tested from a
    ``test`` subpackage is then outside the filter: compiled without counters
    (both backends) or, on the gcov backend, its counters are dropped by
    Bazel's collector. Such files show 0 % or no data although a test ran
    them. The heuristic: no file of the directory has test data, while a
    ``test/`` or ``tests/`` subdirectory of it has.
    """
    dirs_with_data = {name.rsplit("/", 1)[0] if "/" in name else "" for name in with_data}
    suspects = []
    for name in no_data:
        directory = name.rsplit("/", 1)[0] if "/" in name else ""
        if directory in dirs_with_data:
            continue
        tested_from_subdir = any(
            d == f"{directory}/{sub}" or d.startswith(f"{directory}/{sub}/")
            for d in dirs_with_data
            for sub in _TEST_SUBDIRECTORIES
        )
        if tested_from_subdir:
            suspects.append(name)
    return sorted(suspects)


def warn_instrumentation_filter(selection: FileSelection, with_data: set[str]) -> list[str]:
    """Print the ``--instrumentation_filter`` hint for the suspects; returns them."""
    suspects = instrumentation_filter_suspects(selection.baseline_only | selection.unmapped, with_data)
    if suspects:
        print(
            f"WARNING: {len(suspects)} in-scope files have no test data although their directory is tested "
            f"from a test/ or tests/ subdirectory (e.g., {suspects[:5]}). Bazel's default "
            "--instrumentation_filter covers only the packages of the test targets; set "
            "--instrumentation_filter=^//<root package>[/:] in the coverage config (user manual, step 4).",
            file=sys.stderr,
        )
    return suspects


UNMAPPED_NO_DATA = "no-data"
UNMAPPED_DECLARATION_ONLY = "declaration-only"
UNMAPPED_EMPTY_UNIT = "compiled-without-code"


def format_unmapped_files(selection: FileSelection) -> str:
    """``<category>\t<path>`` lines for every in-scope file without coverage data."""
    rows = (
        [(UNMAPPED_NO_DATA, name) for name in selection.unmapped]
        + [(UNMAPPED_DECLARATION_ONLY, name) for name in selection.declaration_only]
        + [(UNMAPPED_EMPTY_UNIT, name) for name in selection.empty_units]
    )
    return "".join(f"{category}\t{name}\n" for category, name in sorted(rows))
