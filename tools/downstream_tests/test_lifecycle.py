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
"""Black-box test for lifecycle's production Linux coverage workflow."""

from pathlib import Path

from _consumer_workspace import clone_consumer, publish_coverage_results, run_bazel


def test_lifecycle_coverage_workflow_reports_measured_coverage(tmp_path: Path) -> None:
    """The checked-in workflow meets its gate and produces a coverage report."""
    workspace = clone_consumer("lifecycle", tmp_path)

    run_bazel(
        workspace,
        "coverage",
        "--config=llvm_cov",
        "//score/...",
        "--lockfile_mode=error",
        "--build_tests_only",
    )
    run_bazel(
        workspace,
        "run",
        "@score_coverage//:generate_coverage_html",
        "--",
        "--yaml",
        "quality/coverage/coverage_justifications.yaml",
        "--archive-dir",
        "coverage_artifacts",
        extra_environment={"COVERAGE_THRESHOLD": "66"},
    )

    publish_coverage_results(workspace, "coverage_artifacts")
