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
"""Coverage gate decisions through the public CLI against LLVM consumer coverage."""

from pathlib import Path

from _blackbox_support import run_bazel, verifies


@verifies("tool_req__coverage_gate_threshold", "tool_req__coverage_gate_exit_codes")
def test_raw_llvm_gate_rejects_high_threshold(consumer_with_llvm_coverage: Path, tmp_path: Path) -> None:
    """The raw gate rejects the partly covered consumer at 100%."""
    result = run_bazel(
        consumer_with_llvm_coverage,
        ["run", "@score_coverage//:generate_coverage_html", "--", str(tmp_path / "coverage")],
        expected_exit_code=1,
        env={"COVERAGE_THRESHOLD": "100"},
    )
    assert "Raw coverage" in result.stderr
    assert "below threshold 100%" in result.stderr
