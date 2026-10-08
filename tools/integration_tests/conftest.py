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
"""Create an isolated consumer workspace for pytest black-box scenarios.

The session workspace is shared, so scenarios that change sources or Bazel
outputs must run serially and restore their changes before returning.
"""

import shutil
from pathlib import Path

import pytest

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
