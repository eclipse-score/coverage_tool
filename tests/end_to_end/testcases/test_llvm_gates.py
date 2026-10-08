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
"""Black-box scenarios for LLVM coverage gate and summary behavior."""

from pathlib import Path

import pytest
from _blackbox_support import (
    JUSTIFICATIONS,
    CoverageReport,
    assert_exit_code,
    generate_report,
    verifies,
)


@pytest.mark.parametrize(
    ("threshold", "expected_exit"),
    [("100", 1), ("10", 0)],
    ids=["fails-at-100-percent", "passes-at-10-percent"],
)
@verifies("tool_req__coverage_gate_exit_codes", derivation="boundary-values")
def test_llvm_effective_gate_uses_reviewed_justifications(
    llvm_report: CoverageReport, threshold: str, expected_exit: int
) -> None:
    """Reviewed justifications make the 10% gate pass and the 100% gate fail."""
    result = generate_report(llvm_report, "--yaml", JUSTIFICATIONS, threshold=threshold)
    assert_exit_code(result, expected_exit)


@pytest.mark.parametrize(
    ("threshold", "expected_exit"),
    [("100", 1), ("10", 0)],
    ids=["raw-fails-at-100-percent", "raw-passes-at-10-percent"],
)
@verifies("tool_req__coverage_gate_metric", "tool_req__coverage_gate_exit_codes")
def test_llvm_without_yaml_gates_on_raw_coverage(
    llvm_report: CoverageReport, threshold: str, expected_exit: int
) -> None:
    """Without a justification file, raw coverage determines both gate outcomes."""
    result = generate_report(llvm_report, threshold=threshold)
    assert_exit_code(result, expected_exit)


@pytest.mark.parametrize(
    ("threshold", "expected_exit"),
    [("100", 1), ("10", 0)],
    ids=["summary-written-on-failure", "summary-written-on-pass"],
)
@verifies("tool_req__coverage_summary_first")
def test_llvm_markdown_summary_is_written_before_the_gate_verdict(
    llvm_report: CoverageReport,
    tmp_path: Path,
    threshold: str,
    expected_exit: int,
) -> None:
    """The requested Markdown summary is complete on both pass and failure."""
    summary = tmp_path / "coverage-summary.md"
    result = generate_report(
        llvm_report,
        "--yaml",
        JUSTIFICATIONS,
        "--summary-md",
        str(summary),
        threshold=threshold,
    )
    assert_exit_code(result, expected_exit)
    assert summary.is_file(), "summary should be written even when the gate fails"
    content = summary.read_text(encoding="utf-8")
    for marker in (
        "## Coverage summary",
        "| Lines |",
        "Raw vs effective",
        "Coverage by directory",
        "Files at exact 0% (3)",
        "| In-scope files without coverage data | 2 |",
        "In-scope files without coverage data (2)",
        "- `src/unused_api.h`",
        "- `src/platform_dep.h`",
        "Declaration-only headers (3)",
        "Compiled sources without code of their own (1)",
        "- `src/empty_unit.cpp`",
        "█",
    ):
        assert marker in content, f"coverage summary is missing {marker!r}"


@verifies("tool_req__coverage_summary_first")
def test_llvm_github_step_summary_appends_without_overwriting_existing_content(
    llvm_report: CoverageReport, tmp_path: Path
) -> None:
    """The CI summary appends coverage while preserving earlier step content."""
    summary = tmp_path / "step-summary.md"
    summary.write_text("# Earlier step\n", encoding="utf-8")
    result = generate_report(
        llvm_report,
        "--yaml",
        JUSTIFICATIONS,
        env={"GITHUB_STEP_SUMMARY": str(summary)},
    )
    assert_exit_code(result, 0)
    content = summary.read_text(encoding="utf-8")
    assert "# Earlier step" in content
    assert "## Coverage summary" in content
