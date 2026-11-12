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
"""Read Bazel report inputs and resolve scope files and toolchain paths."""

import sys
from pathlib import Path
from typing import Protocol


class RunfilesLike(Protocol):
    """The part of ``python.runfiles.Runfiles`` this module uses; tests provide fakes."""

    def Rlocation(self, path: str) -> str | None:  # noqa: N802  # pylint: disable=invalid-name
        """Resolve a runfiles path to an absolute path, or None."""


def read_reports_file(reports_file: Path) -> list[Path]:
    """Read per-test output paths, preserving their order and relative paths."""
    with open(reports_file, encoding="utf-8") as f:
        return [Path(line.strip()) for line in f if line.strip()]


def resolve_tool(
    runfiles: RunfilesLike | None,
    flag_value: str | None,
    fallback_rlocation: str,
) -> Path | None:
    """Resolve a tool path from the explicit argument or the backend's fallback.

    For each candidate, prefer its Bazel runfiles location and then try it
    as a plain filesystem path. The explicit argument takes precedence.
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
