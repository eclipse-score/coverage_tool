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

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

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
                        archive.writestr("meta/meta.json", '{"object_files": []}')
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
            with zipfile.ZipFile(llvm, "w") as archive:
                archive.writestr("meta/meta.json", '{"object_files": []}')
                archive.writestr("profdata/target.profdata", b"profile")
            gcov = root / "gcov.dat"
            gcov.write_text("SF:a.cpp\nend_of_record\n")
            unknown = root / "unknown.dat"
            unknown.write_text("unsupported format")
            reports = root / "reports.txt"
            for inputs, message in (([llvm, gcov], "cannot be combined"), ([unknown], "Unrecognized coverage input")):
                reports.write_text("\n".join(map(str, inputs)))
                with self.subTest(inputs=inputs), self.assertRaisesRegex(ValueError, message):
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


@pytest.mark.parametrize(
    "members",
    [
        pytest.param({}, id="empty-zip"),
        # LCOV-looking text inside an unrelated ZIP must not be accepted either.
        pytest.param(
            {"unrelated.txt": "SF:src/a.cpp\nDA:1,1\nend_of_record\n"},
            id="unrelated-zip",
        ),
        pytest.param({"meta/meta.json": '{"object_files": []}'}, id="missing-profile"),
        pytest.param({"profdata/target.profdata": "profile"}, id="missing-metadata"),
    ],
)
def test_unrecognized_archive_fails_without_writing_a_report(
    fs: FakeFilesystem, capsys: pytest.CaptureFixture[str], members: dict[str, str]
) -> None:
    """An unknown archive must fail through the real entry point without creating a report."""
    fs.create_dir("/workspace")
    contribution = Path("/workspace/coverage.dat")
    reports = Path("/workspace/reports.txt")
    output = Path("/workspace/report.zip")
    with zipfile.ZipFile(contribution, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    reports.write_text(str(contribution), encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        generator.main(["--reports_file", str(reports), "--output_file", str(output), "--workspace_root", "/workspace"])

    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert "Unrecognized coverage input" in stderr
    assert str(contribution) in stderr
    assert not output.exists()


@pytest.mark.parametrize("tool_args", [(), ("--gcov=unused/gcov",)], ids=["llvm", "gcov"])
def test_empty_report_list_writes_an_empty_archive(fs: FakeFilesystem, tool_args: tuple[str, ...]) -> None:
    """Both real backends accept a run without measurements, unlike an invalid ZIP."""
    fs.create_dir("/workspace")
    reports = Path("/workspace/reports.txt")
    output = Path("/workspace/report.zip")
    reports.write_text("", encoding="utf-8")

    generator.main(
        ["--reports_file", str(reports), "--output_file", str(output), "--workspace_root", "/workspace", *tool_args]
    )

    with zipfile.ZipFile(output) as report:
        assert report.namelist() == []
