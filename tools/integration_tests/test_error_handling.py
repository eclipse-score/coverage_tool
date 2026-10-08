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
"""Black-box checks of invalid coverage configuration through the public CLI."""

import os
import shutil
import subprocess
from pathlib import Path

from attribute_plugin import add_test_properties


@add_test_properties(
    partially_verifies=["tool_req__coverage_gate_no_verdict"],
    test_type="fault-injection",
    derivation_technique="error-guessing",
)
def test_non_numeric_threshold_returns_no_verdict(consumer_workspace: Path) -> None:
    """An invalid threshold gives exit 2 and its cause, even before collecting coverage."""
    bazel = shutil.which("bazel")
    assert bazel, "Bazel must be available on PATH to run the consumer scenario"
    environment = os.environ.copy()
    environment.pop("GITHUB_STEP_SUMMARY", None)
    environment["COVERAGE_THRESHOLD"] = "lenient"
    result = subprocess.run(
        [bazel, "run", "@score_coverage//:generate_coverage_html"],
        cwd=consumer_workspace,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 2, f"expected no-verdict exit 2, got {result.returncode}:\n{output}"
    assert "COVERAGE_THRESHOLD must be a number, got 'lenient'" in output
