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

"""Read Bazel reporter inputs and resolve tool and source files for both backends."""

import os
import sys
from pathlib import Path
from typing import Protocol


class RunfilesLike(Protocol):
    """The part of ``python.runfiles.Runfiles`` this module uses; tests provide fakes."""

    def Rlocation(self, path: str) -> str | None:  # noqa: N802  # pylint: disable=invalid-name
        """Resolve a runfiles path to an absolute path, or None."""


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
    """Create ``source_root/<recorded path>`` links to the real sources.

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


def read_reports_file(reports_file: Path) -> list[str]:
    """Read the reports file listing all per-test coverage outputs."""
    with open(reports_file, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def resolve_tool(
    runfiles: RunfilesLike | None,
    flag_value: str | None,
    fallback_rlocation: str,
) -> Path | None:
    """Resolve a coverage tool path.

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
