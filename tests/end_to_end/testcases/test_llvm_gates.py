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

import pytest
from _blackbox_support import run_bazel, verifies


@verifies("tool_req__coverage_gate_threshold", "tool_req__coverage_gate_exit_codes")
@pytest.mark.parametrize("threshold, expected_exit_code", [(10, 0), (100, 1)], ids=["passes", "fails"])
@pytest.mark.parametrize("with_justifications", [False, True], ids=["raw", "effective"])
def test_llvm_gate_decision(
    consumer_with_llvm_coverage: Path,
    with_justifications: bool,
    threshold: int,
    expected_exit_code: int,
) -> None:
    """The partly covered consumer passes at 10% and fails at 100% in either gate mode."""
    args = ["run", "@score_coverage//:generate_coverage_html"]
    if with_justifications:
        args.extend(["--", "--yaml", "tools/coverage/coverage_justifications.yaml"])
    result = run_bazel(
        consumer_with_llvm_coverage,
        args,
        expected_exit_code=expected_exit_code,
        env={"COVERAGE_THRESHOLD": str(threshold)},
    )
    if expected_exit_code == 1:
        metric = "Effective" if with_justifications else "Raw"
        assert f"{metric} coverage" in result.stderr
        assert "below threshold" in result.stderr
