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

"""Package coverage outputs into the ZIP format shared by collection and reporting."""

import os
import zipfile
from pathlib import Path


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
