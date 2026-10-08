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
"""An isolated consumer workspace for local end-to-end pytest cases."""

import shutil
from pathlib import Path

import pytest

# This local-only target needs symlinked runfiles: resolve() follows conftest.py
# back into the checkout. Copied runfiles and remote execution cannot supply
# the full repository tree or the host Bazel installation used by the fixtures.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CONSUMER_WORKSPACE_DIRECTORY = "tests/end_to_end/consumer"


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
    if not (_REPOSITORY_ROOT / "MODULE.bazel").is_file():
        pytest.fail(
            "Black-box tests require local execution with symlinked runfiles pointing "
            f"into the source checkout; MODULE.bazel is missing at {_REPOSITORY_ROOT}",
            pytrace=False,
        )
    if shutil.which("bazel") is None:
        pytest.fail("Black-box tests require the host Bazel installation on PATH", pytrace=False)
    root = tmp_path_factory.mktemp("score-coverage-blackbox") / "repo"
    shutil.copytree(_REPOSITORY_ROOT, root, ignore=_ignore_generated_workspace_files)
    return root / _CONSUMER_WORKSPACE_DIRECTORY
