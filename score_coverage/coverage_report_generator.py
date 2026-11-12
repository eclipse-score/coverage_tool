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
"""Dispatch Bazel's combined coverage report to the backend matching its inputs."""

import argparse
import sys
import zipfile
from pathlib import Path

from score_coverage import gcov_coverage_report_generator, llvm_coverage_report_generator
from score_coverage.report_inputs import read_reports_file


def detect_backend(reports_file: Path) -> str | None:
    """Recognize native LLVM archives or LCOV; never combine the two formats."""
    formats = set()
    for path in read_reports_file(reports_file):
        # Bazel adds LCOV baselines even for native LLVM measurements. They
        # describe measurable sources, not the format of test measurements.
        if path.name == "baseline_coverage.dat":
            continue
        # Collectors can leave empty outputs for tests without coverage data.
        # Missing inputs are handled by the backend's existing diagnostics.
        if not path.is_file() or not path.stat().st_size:
            continue
        if zipfile.is_zipfile(path):
            if not llvm_coverage_report_generator.is_coverage_report(path):
                raise ValueError(f"Unrecognized coverage input: {path}")
            formats.add("llvm")
        else:
            with path.open(encoding="utf-8") as stream:
                if not any(line.startswith("SF:") for line in stream):
                    raise ValueError(f"Unrecognized coverage input: {path}")
            formats.add("gcov")
    if len(formats) > 1:
        raise ValueError("LLVM archives and LCOV inputs cannot be combined in one report")
    return next(iter(formats), None)


def main(argv: list[str] | None = None) -> None:
    """Preserve the backend CLI and choose its implementation from coverage data."""
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--reports_file", type=Path)
    parser.add_argument("--gcov")
    args, _ = parser.parse_known_args(argv)
    try:
        backend = detect_backend(args.reports_file) if args.reports_file is not None else None
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    # Empty runs carry no format signature. The wrapper already supplies the
    # matching tool arguments; they also select the appropriate CLI help.
    if backend is None:
        backend = "gcov" if args.gcov else "llvm"
    implementation = gcov_coverage_report_generator if backend == "gcov" else llvm_coverage_report_generator
    implementation.main(argv)


if __name__ == "__main__":
    main()
