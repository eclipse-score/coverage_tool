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
"""Run coverage tests against real consumer repositories."""

from dataclasses import dataclass
from pathlib import Path

import pytest
from _consumer_workspace import clone_consumer, retain_coverage_results, run_bazel, verify_coverage_results


@dataclass(frozen=True)
class Consumer:
    """Arguments needed to generate coverage reports for a downstream repository."""

    coverage_args: tuple[str, ...] = ("--config=llvm_cov", "--build_tests_only", "--", "//score/...")
    justification_file: str | None = "tools/coverage/coverage_justifications.yaml"


CONSUMERS = {
    "baselibs": Consumer(
        coverage_args=(
            "--config=llvm_cov",
            "--build_tests_only",
            "--",
            "//score/...",
            # This test expects compact JSON, but the coverage config uses pretty printing.
            "-//score/json/internal/writer/vajson:vajson_serialize_test",
            # Exclusions from baselibs' LLVM coverage workflow: these tests
            # require GCC semantics or fail with static linking.
            "-//score/language/safecpp/aborts_upon_exception/...",
            "-//score/language/safecpp/safe_math/details:floating_point_environment_test",
            "-//score/os/linux/utils/test:network_interface_test",
        ),
    ),
    "inc_security_crypto": Consumer(),
    "inc_someip_gateway": Consumer(
        coverage_args=("--build_tests_only", "--", "//..."),
        justification_file=None,
    ),
    "kyron": Consumer(
        coverage_args=("--config=llvm_cov", "--build_tests_only", "--", "//src/..."),
    ),
    "lifecycle": Consumer(
        justification_file="quality/coverage/coverage_justifications.yaml",
    ),
    "logging": Consumer(justification_file=None),
    "persistency": Consumer(justification_file="quality/coverage/coverage_justifications.yaml"),
    "time": Consumer(),
}


@pytest.mark.parametrize("consumer,settings", CONSUMERS.items(), ids=CONSUMERS)
def test_consumer_coverage_workflow_reports_measured_coverage(
    tmp_path: Path, consumer: str, settings: Consumer
) -> None:
    """Each consumer must produce and retain a report with measured coverage."""
    workspace = clone_consumer(consumer, tmp_path)
    if consumer == "inc_someip_gateway":
        # The gateway's test wrappers use the production workflow's host selection.
        (workspace / ".bazel_config").write_text("host\n", encoding="utf-8")

    run_bazel(workspace, "coverage", *settings.coverage_args)
    report_arguments = ["--summary-md", "coverage_summary.md", "--archive-dir", "coverage_artifact"]
    if settings.justification_file:
        report_arguments.extend(("--yaml", settings.justification_file))

    # Keep any report artifacts even if report generation fails.
    try:
        run_bazel(
            workspace,
            "run",
            "@score_coverage//:generate_coverage_html",
            "--",
            *report_arguments,
            # Verify measured coverage below without imposing a consumer-specific gate.
            extra_environment={"COVERAGE_THRESHOLD": "0"},
        )
    finally:
        retain_coverage_results(workspace, "coverage_artifact")

    verify_coverage_results(workspace, "coverage_artifact")
