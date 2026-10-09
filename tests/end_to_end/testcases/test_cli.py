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
"""A CLI case exercising the end-to-end pytest infrastructure."""

from pathlib import Path

from _blackbox_support import assert_exit_code, run_bazel, verifies


@verifies("tool_req__coverage_gate_no_verdict")
def test_missing_report_returns_no_verdict(consumer_workspace: Path) -> None:
    """A consumer without coverage data gets exit 2 and a diagnostic explaining how to collect it."""
    report = consumer_workspace / "bazel-out/_coverage/_coverage_report.dat"
    report.unlink(missing_ok=True)
    result = run_bazel(
        consumer_workspace,
        ["run", "@score_coverage//:generate_coverage_html"],
        env={"COVERAGE_THRESHOLD": "10"},
    )
    assert_exit_code(result, 2)
    output = result.stdout + result.stderr
    assert "Coverage report not found" in output
    assert "Run 'bazel coverage" in output
