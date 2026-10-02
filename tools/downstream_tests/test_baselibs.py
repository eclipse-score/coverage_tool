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

from _consumer_workspace import clone_consumer, publish_coverage_results, run_bazel


def test_baselibs_coverage_workflow_reports_measured_coverage(tmp_path: Path) -> None:
    """The checked-in baselibs workflow produces a non-empty coverage report."""
    workspace = clone_consumer("baselibs", tmp_path)

    run_bazel(
        workspace,
        "coverage",
        "--lockfile_mode=error",
        "--config=llvm_cov",
        "--build_tests_only",
        "--",
        "//score/...",
        # This upstream-main test currently fails under the coverage config
        # because its compact-JSON expectations conflict with default pretty printing.
        "-//score/json/internal/writer/vajson:vajson_serialize_test",
        "-//score/language/safecpp/aborts_upon_exception/...",
        "-//score/language/safecpp/safe_math/details:floating_point_environment_test",
        "-//score/os/linux/utils/test:network_interface_test",
    )
    run_bazel(
        workspace,
        "run",
        "--lockfile_mode=error",
        "@score_coverage//:generate_coverage_html",
        "--",
        "--yaml",
        "tools/coverage/coverage_justifications.yaml",
        "--testlogs-subdir",
        "score",
        "--archive-dir",
        "coverage_artifact",
        extra_environment={"COVERAGE_THRESHOLD": "0"},
    )

    publish_coverage_results(workspace, "coverage_artifact")
