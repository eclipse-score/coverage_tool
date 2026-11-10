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
"""Original per-test measurements travel with the existing coverage artifacts."""

import io
import json
import zipfile
from pathlib import Path

import pytest
from _blackbox_support import run_bazel, verifies


@pytest.mark.parametrize("backend", ["llvm_cov", "gcov"])
@verifies("tool_req__coverage_report_outputs", "tool_req__coverage_artifacts")
def test_measurements_remain_unmerged_in_report_and_upload_artifacts(
    consumer_workspace: Path, tmp_path: Path, backend: str
) -> None:
    """Two tests with two cached runs keep four original inputs through report archiving."""
    targets = ["//src:coverable_test", "//lib/test:cross_pkg_test"]
    coverage = ["coverage", f"--config={backend}", *targets, "--runs_per_test=2", "--cache_test_results=yes"]
    run_bazel(consumer_workspace, coverage)
    run_bazel(consumer_workspace, coverage)
    original = {}
    with zipfile.ZipFile(consumer_workspace / "bazel-out/_coverage/_coverage_report.dat") as report:
        paths = report.read("test_reports/paths.txt").decode().splitlines()
        assert len(paths) == 4
        for number, path in enumerate(paths):
            member = f"test_reports/{number:08d}/{Path(path).name}"
            original[member] = report.read(member)
            assert original[member] == (consumer_workspace / path).read_bytes()
            if backend == "llvm_cov":
                with zipfile.ZipFile(io.BytesIO(original[member])) as per_test:
                    assert json.loads(per_test.read("meta/meta.json"))["test_target"] in targets
            else:
                assert b"SF:" in original[member]
    artifacts = tmp_path / "artifacts"
    run_bazel(
        consumer_workspace,
        [
            "run",
            "@score_coverage//:generate_coverage_html",
            "--",
            "--archive-dir",
            str(artifacts),
        ],
        env={"COVERAGE_THRESHOLD": "0"},
    )
    assert (artifacts / "test_reports/paths.txt").read_text().splitlines() == paths
    for member, data in original.items():
        assert (artifacts / member).read_bytes() == data
