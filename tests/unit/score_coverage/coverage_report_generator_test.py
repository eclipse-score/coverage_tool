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
"""The common Bazel entry point preserves backend dispatch and rejects mixed data."""

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from score_coverage import coverage_report_generator as generator


class DispatchTest(unittest.TestCase):
    """Use actual coverage signatures while replacing expensive backend execution."""

    def test_dispatch_preserves_backend_arguments(self):
        """The inputs choose the backend; all existing arguments reach it unchanged."""
        for backend in ("llvm", "gcov"):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                contribution = root / "coverage.dat"
                if backend == "llvm":
                    with zipfile.ZipFile(contribution, "w") as archive:
                        archive.writestr("profdata/target.profdata", b"profile")
                else:
                    contribution.write_text("TN:test\nSF:src/a.cpp\nDA:1,1\nend_of_record\n")
                reports = root / "reports.txt"
                baseline = root / "baseline_coverage.dat"
                baseline.write_text("SF:src/uncovered.cpp\nDA:1,0\nend_of_record\n")
                reports.write_text(f"{contribution}\n{baseline}\n")
                argv = ["--reports_file", str(reports), "--output_file", "result.zip"]
                implementation = (
                    generator.llvm_coverage_report_generator
                    if backend == "llvm"
                    else generator.gcov_coverage_report_generator
                )
                with mock.patch.object(implementation, "main") as run:
                    generator.main(argv)
                run.assert_called_once_with(argv)

    def test_mixed_and_unknown_inputs_are_rejected_before_reporting(self):
        """Incompatible or unrecognized inputs must not silently lose coverage."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            llvm = root / "llvm.dat"
            with zipfile.ZipFile(llvm, "w"):
                pass
            gcov = root / "gcov.dat"
            gcov.write_text("SF:a.cpp\nend_of_record\n")
            unknown = root / "unknown.dat"
            unknown.write_text("unsupported format")
            reports = root / "reports.txt"
            for inputs in ([llvm, gcov], [unknown]):
                reports.write_text("\n".join(map(str, inputs)))
                with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                    generator.detect_backend(reports)

    def test_empty_inputs_use_existing_tool_arguments(self):
        """Without data, tool arguments retain backend-specific empty-run handling."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "empty.dat"
            empty.touch()
            reports = root / "reports.txt"
            reports.write_text(f"{empty}\n{root / 'missing.dat'}\n")
            for tools, implementation in (
                ([], generator.llvm_coverage_report_generator),
                (["--gcov=tool/gcov"], generator.gcov_coverage_report_generator),
            ):
                argv = ["--reports_file", str(reports), *tools]
                with self.subTest(tools=tools), mock.patch.object(implementation, "main") as run:
                    generator.main(argv)
                run.assert_called_once_with(argv)

    def test_invalid_input_exits_without_invoking_a_backend(self):
        """The command-line entry reports invalid input as a usage error."""
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory) / "missing-reports.txt"
            with mock.patch("sys.stderr"), self.assertRaises(SystemExit) as error:
                generator.main(["--reports_file", str(reports)])
            self.assertEqual(error.exception.code, 2)

    def test_help_is_delegated_without_reading_inputs(self):
        """Backend argument help remains available without a reports list."""
        with mock.patch.object(generator.llvm_coverage_report_generator, "main") as run:
            generator.main(["--help"])
        run.assert_called_once_with(["--help"])
