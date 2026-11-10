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
"""Archived coverage outputs and justification results from the public CLI."""

from pathlib import Path
from zipfile import ZipFile

import pytest
from _blackbox_support import EXPECTED_CPP_UNMAPPED, lcov_records, verifies


@verifies("tool_req__coverage_artifacts", "tool_req__coverage_gate_threshold", "tool_req__coverage_gate_exit_codes")
def test_archive_directory_contains_coverage_reports(llvm_artifacts: Path) -> None:
    """The effective gate passes at 10% and archives HTML, LCOV and the justification summary."""
    archive = llvm_artifacts / "artifacts"
    for relative_path in ("coverage_linux/index.html", "coverage_report.dat", "justification_report/summary.txt"):
        assert (archive / relative_path).is_file(), f"Missing archived report: {relative_path}"


@verifies("tool_req__coverage_artifacts")
def test_zip_archive_contains_coverage_reports(llvm_artifacts: Path) -> None:
    """The zip includes the reports below its portable artifacts/ root."""
    with ZipFile(llvm_artifacts / "coverage_artifacts.zip") as archive:
        for relative_path in ("coverage_linux/index.html", "coverage_report.dat", "justification_report/summary.txt"):
            assert f"artifacts/{relative_path}" in archive.namelist()


@verifies("tool_req__coverage_artifacts")
@pytest.mark.parametrize("archive_format", ["directory", "zip"])
def test_archived_lcov_preserves_collected_coverage(
    llvm_artifacts: Path, llvm_lcov: dict[str, list[str]], archive_format: str
) -> None:
    """Archiving preserves the measured line and branch records in either output format."""
    if archive_format == "directory":
        content = (llvm_artifacts / "artifacts/coverage_report.dat").read_text(encoding="utf-8")
    else:
        with ZipFile(llvm_artifacts / "coverage_artifacts.zip") as archive:
            content = archive.read("artifacts/coverage_report.dat").decode("utf-8")
    assert lcov_records(content) == llvm_lcov


@verifies("tool_req__coverage_report_unmapped", "tool_req__coverage_artifacts")
def test_archived_unmapped_sources_have_expected_categories(llvm_artifacts: Path) -> None:
    """The LLVM archive lists each unmapped finding once with its category."""
    records = (llvm_artifacts / "artifacts/unmapped_files.txt").read_text(encoding="utf-8").splitlines()
    assert sorted(records) == sorted(EXPECTED_CPP_UNMAPPED)
