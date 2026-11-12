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
"""Stage source files and package coverage reports independently of the backend."""

import os
import zipfile
from pathlib import Path

from score_coverage.report_inputs import RunfilesLike


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
    """Create ``source_root/<raw source path>`` links to the real sources.

    Renderers read sources through this directory using the paths recorded
    in their coverage inputs. Absolute paths are left unchanged. Returns
    the canonical names whose source could not be located.
    """
    missing = []
    for raw, canonical in sorted(staged.items()):
        if raw.startswith("/"):
            continue  # an absolute source path is read as it is
        real = resolve_source(runfiles, canonical, workspace_root)
        if real is None:
            missing.append(canonical)
            continue
        link = source_root / raw
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink() and not link.exists():
            link.symlink_to(os.path.realpath(real))
    return sorted(set(missing))


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
