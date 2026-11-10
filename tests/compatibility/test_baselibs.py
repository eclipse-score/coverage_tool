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
"""Black-box test for baselibs' production LLVM coverage workflow."""

from pathlib import Path

from _consumer_workspace import clone_consumer, retain_coverage_results, run_bazel, verify_coverage_results


def test_baselibs_coverage_workflow_reports_measured_coverage(tmp_path: Path) -> None:
    """The checked-in baselibs workflow produces a non-empty coverage report."""
    workspace = clone_consumer("baselibs", tmp_path)

    run_bazel(
        workspace,
        "coverage",
        # The local coverage_tool override changes the consumer's dependency
        # graph. Update its lockfile while evaluating only extensions needed
        # for coverage; `bazel mod deps` also fetches unrelated container inputs.
        "--lockfile_mode=update",
        "--config=llvm_cov",
        "--build_tests_only",
        "--",
        "//score/...",
        "-//score/language/safecpp/aborts_upon_exception/...",
        "-//score/language/safecpp/safe_math/details:floating_point_environment_test",
        "-//score/os/linux/utils/test:network_interface_test",
    )
    # The generator assembles artifacts before returning a gate failure.
    try:
        run_bazel(
            workspace,
            "run",
            "--lockfile_mode=error",
            "@score_coverage//:generate_coverage_html",
            "--",
            "--yaml",
            "tools/coverage/coverage_justifications.yaml",
            "--summary-md",
            "coverage_summary.md",
            "--testlogs-subdir",
            "score",
            "--archive-dir",
            "coverage_artifact",
            extra_environment={"COVERAGE_THRESHOLD": "0"},
        )
    finally:
        retain_coverage_results(workspace, "coverage_artifact")

    verify_coverage_results(workspace, "coverage_artifact")
