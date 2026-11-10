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
"""The checked-in consumer workspace for local end-to-end pytest cases."""

import os
import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest
from _blackbox_support import lcov_records, run_bazel

# This local-only target needs symlinked runfiles: resolve() follows conftest.py
# back into the checkout. Copied runfiles and remote execution cannot supply
# the consumer workspace or the host Bazel installation used by the fixtures.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CONSUMER_WORKSPACE_DIRECTORY = "tests/end_to_end/consumer"


@pytest.fixture(scope="session")
def consumer_workspace() -> Path:
    """Reuse the consumer's Bazel outputs, including its extracted toolchains."""
    if not (_REPOSITORY_ROOT / "MODULE.bazel").is_file():
        pytest.fail(
            "Black-box tests require local execution with symlinked runfiles pointing "
            f"into the source checkout; MODULE.bazel is missing at {_REPOSITORY_ROOT}",
            pytrace=False,
        )
    if shutil.which("bazel") is None:
        pytest.fail("Black-box tests require the host Bazel installation on PATH", pytrace=False)
    return _REPOSITORY_ROOT / _CONSUMER_WORKSPACE_DIRECTORY


@pytest.fixture(scope="session")
def consumer_with_llvm_coverage(consumer_workspace: Path) -> Path:
    """Run LLVM coverage once and return the consumer containing the generated report."""
    run_bazel(consumer_workspace, ["coverage", "--config=llvm_cov", "//...", "--build_tests_only"])
    assert (consumer_workspace / "bazel-out/_coverage/_coverage_report.dat").is_file()
    return consumer_workspace


@pytest.fixture(scope="session")
def llvm_lcov(consumer_with_llvm_coverage: Path) -> dict[str, list[str]]:
    """Read the shared LLVM report without running the CLI or rebuilding coverage."""
    with ZipFile(consumer_with_llvm_coverage / "bazel-out/_coverage/_coverage_report.dat") as report:
        return lcov_records(report.read("lcov_report/lcov.dat").decode("utf-8"))


@pytest.fixture(scope="session")
def llvm_artifacts(consumer_with_llvm_coverage: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate both archive formats once, with fresh HTML and artifact destinations."""
    output = tmp_path_factory.mktemp("llvm_artifacts")
    archive = output / "coverage_artifacts.zip"
    try:
        run_bazel(
            consumer_with_llvm_coverage,
            [
                "run",
                "@score_coverage//:generate_coverage_html",
                "--",
                "--yaml",
                "tools/coverage/coverage_justifications.yaml",
                "--archive-dir",
                str(output / "artifacts"),
                "--archive",
                str(archive.with_suffix("")),
                str(output / "coverage_linux"),
            ],
            env={"COVERAGE_THRESHOLD": "10"},
        )
    finally:
        # The CLI can produce an archive before returning a failed gate verdict.
        # Publish it for CI diagnostics even if the exit-code assertion failed.
        undeclared_outputs = os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR")
        if undeclared_outputs and archive.is_file():
            shutil.copyfile(archive, Path(undeclared_outputs) / archive.name)
    return output
