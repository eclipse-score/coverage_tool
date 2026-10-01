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
"""Resolve source files from Bazel runfiles and stage them for report renderers."""

import os
from pathlib import Path
from typing import Protocol


class RunfilesLike(Protocol):
    """The part of ``python.runfiles.Runfiles`` this module uses; tests provide fakes."""

    def Rlocation(self, path: str) -> str | None:  # noqa: N802  # pylint: disable=invalid-name
        """Resolve a runfiles path to an absolute path, or None."""


def resolve_source(runfiles: RunfilesLike, canonical: str, workspace_root: str) -> str | None:
    """Absolute path of an in-scope source: from Bazel runfiles, else the workspace."""
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
    """Recreate recorded source paths under ``source_root`` as links.

    ``staged`` maps each path recorded in coverage data to its canonical source
    path. Renderers use the recorded path to read source text, so the links
    reproduce that layout beneath ``source_root``. Return canonical paths that
    could not be found in runfiles or the workspace.
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
