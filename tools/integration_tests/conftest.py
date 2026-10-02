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
"""Shared consumer workspaces and backend reports for black-box scenarios.

The consumer copy is created once per pytest run. LLVM and gcov reports are
also collected once each, then individual scenarios pass those saved reports
to the public report-generation command with their own options.
"""

import shutil
from pathlib import Path

import pytest
from _blackbox_support import CoverageReport, collect_report

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CONSUMER_WORKSPACE_DIRECTORY = "integration_tests"


def _ignore_generated_workspace_files(_directory: str, names: list[str]) -> set[str]:
    """Keep the consumer copy limited to source and test fixtures."""
    generated = {
        ".git",
        ".ub_cache",
        ".venv",
        ".vscode",
        ".pytest_cache",
        ".ruff_cache",
        ".integration-test-venv",
        "__pycache__",
        "external",
        "_build",
        "coverage_artifact",
        "coverage_artifacts.zip",
        "coverage_gcov",
        "coverage_linux",
        "gcov_artifacts_dir",
        "gcov_run.log",
        "gcov_summary.md",
        "lcov.dat",
        "link_check",
        "test-reports",
        "tests-report",
        "typo_dir",
        "user.bazelrc",
    }
    return {name for name in names if name in generated or name.startswith("bazel-")}


@pytest.fixture(scope="session")
def consumer_workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Copy sources so nested Bazel outputs and source fault injection stay isolated."""
    root = tmp_path_factory.mktemp("score-coverage-blackbox") / "repo"
    shutil.copytree(_REPOSITORY_ROOT, root, ignore=_ignore_generated_workspace_files)
    return root / _CONSUMER_WORKSPACE_DIRECTORY


@pytest.fixture(scope="session")
def llvm_report(consumer_workspace: Path, tmp_path_factory: pytest.TempPathFactory) -> CoverageReport:
    """Collect LLVM coverage for every target, including C++ and Rust tests."""
    return collect_report(
        consumer_workspace,
        "llvm_cov",
        ["//..."],
        tmp_path_factory.mktemp("llvm-report") / "coverage_report.dat",
    )


@pytest.fixture(scope="session")
def gcov_report(consumer_workspace: Path, tmp_path_factory: pytest.TempPathFactory) -> CoverageReport:
    """Collect gcov for //src/... and //lib/...; LLVM covers Rust separately."""
    return collect_report(
        consumer_workspace,
        "gcov",
        ["//src/...", "//lib/..."],
        tmp_path_factory.mktemp("gcov-report") / "coverage_report.dat",
    )
