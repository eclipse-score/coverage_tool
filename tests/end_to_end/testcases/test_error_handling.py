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
"""Black-box fault-injection scenarios for malformed coverage inputs."""

from pathlib import Path

from _blackbox_support import (
    JUSTIFICATIONS,
    CoverageReport,
    assert_exit_code,
    fault_injection,
    generate_report,
    run_bazel,
    summary_metric,
)


@fault_injection("tool_req__coverage_gate_no_verdict")
def test_corrupt_llvm_report_returns_no_verdict(llvm_report: CoverageReport) -> None:
    """A corrupt coverage archive returns exit 2 even with a permissive threshold."""
    report_path = llvm_report.install()
    report_path.write_text("this is not a zip archive", encoding="utf-8")
    try:
        result = run_bazel(
            llvm_report.workspace,
            ["run", "@score_coverage//:generate_coverage_html"],
            env={"COVERAGE_THRESHOLD": "0"},
        )
    finally:
        # Restore the shared session report so later scenarios see valid input.
        llvm_report.install()
    assert_exit_code(result, 2)


@fault_injection("tool_req__coverage_gate_no_verdict", derivation="boundary-values")
def test_non_numeric_threshold_returns_no_verdict(llvm_report: CoverageReport) -> None:
    """An invalid threshold is rejected with exit 2 instead of passing the gate."""
    result = generate_report(llvm_report, threshold="lenient")
    assert_exit_code(result, 2)


@fault_injection("tool_req__coverage_just_unknown_id")
def test_unknown_justification_marker_is_reported_and_not_credited(llvm_report: CoverageReport, tmp_path: Path) -> None:
    """An unrecognized code marker is reported and leaves effective equal to raw."""
    source = llvm_report.workspace / "src/coverable.cpp"
    original = source.read_text(encoding="utf-8")
    valid_marker = "COV_JUSTIFIED itest-positive-branch"
    unknown_marker = "COV_JUSTIFIED itest-typo-branch"
    assert original.count(valid_marker) == 1, "fault injection expects one known marker in coverable.cpp"
    source.write_text(original.replace(valid_marker, unknown_marker), encoding="utf-8")
    output = tmp_path / "typo-artifacts"
    try:
        result = generate_report(
            llvm_report,
            "--yaml",
            JUSTIFICATIONS,
            "--archive-dir",
            str(output),
        )
    finally:
        # The consumer workspace is shared by the other LLVM scenarios.
        source.write_text(original, encoding="utf-8")
    assert_exit_code(result, 0)
    assert "references unknown ID 'itest-typo-branch'" in result.stdout + result.stderr
    summary = (output / "justification_report" / "summary.txt").read_text(encoding="utf-8")
    assert summary_metric(summary, "Effective line coverage") == summary_metric(summary, "Raw line coverage")
