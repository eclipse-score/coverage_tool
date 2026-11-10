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
"""CLI verdicts and diagnostics with isolated report inputs."""

import json
import os
import subprocess
from pathlib import Path
from shutil import copyfile

from _blackbox_support import verifies

_REPORT_PATH = Path("bazel-out/_coverage/_coverage_report.dat")


def _run_cli(workspace: Path, *args: str, threshold: str = "0") -> subprocess.CompletedProcess[str]:
    """Launch the Bazel-built CLI with the workspace environment normally set by bazel run."""
    # Keep the runfiles path intact so the launcher can find its packaged dependencies.
    executable = Path(__file__).absolute().parents[3] / "score_coverage/generate_coverage_html"
    env = os.environ.copy()
    env.update(BUILD_WORKSPACE_DIRECTORY=str(workspace), COVERAGE_THRESHOLD=threshold)
    env.pop("GITHUB_STEP_SUMMARY", None)
    return subprocess.run([executable, *args], cwd=workspace, env=env, capture_output=True, text=True, check=False)


@verifies("tool_req__coverage_gate_no_verdict")
def test_missing_report_returns_no_verdict(tmp_path: Path) -> None:
    """An empty workspace gets exit 2 and instructions for collecting coverage."""
    result = _run_cli(tmp_path)
    assert result.returncode == 2, result.stderr
    assert "Coverage report not found" in result.stderr
    assert "Run 'bazel coverage" in result.stderr


@verifies("tool_req__coverage_gate_no_verdict", "tool_req__coverage_gate_exit_codes")
def test_corrupt_report_returns_no_verdict(tmp_path: Path) -> None:
    """A corrupt report cannot yield a passing verdict even at a zero threshold."""
    report = tmp_path / _REPORT_PATH
    report.parent.mkdir(parents=True)
    report.write_text("not a zip archive", encoding="utf-8")

    result = _run_cli(tmp_path)
    assert result.returncode == 2, result.stderr
    assert "not a score_coverage report zip" in result.stderr


@verifies("tool_req__coverage_gate_threshold", "tool_req__coverage_gate_exit_codes")
def test_invalid_threshold_returns_no_verdict(tmp_path: Path) -> None:
    """A nonnumeric threshold is diagnosed before the CLI looks for coverage data."""
    result = _run_cli(tmp_path, threshold="lenient")
    assert result.returncode == 2, result.stderr
    assert "COVERAGE_THRESHOLD must be a number" in result.stderr


@verifies("tool_req__coverage_just_unknown_id")
def test_unknown_marker_warns_without_increasing_coverage(tmp_path: Path, consumer_with_llvm_coverage: Path) -> None:
    """The fixture's uncovered line refers to an ID absent from the supplied YAML."""
    report = tmp_path / _REPORT_PATH
    report.parent.mkdir(parents=True)
    copyfile(consumer_with_llvm_coverage / _REPORT_PATH, report)
    source = Path("src/coverable.cpp")
    (tmp_path / source.parent).mkdir()
    copyfile(consumer_with_llvm_coverage / source, tmp_path / source)
    (tmp_path / "justifications.yaml").write_text("version: 1\njustifications: []\n", encoding="utf-8")
    # The archive needs a test logs directory even when no JUnit files are needed for this case.
    (tmp_path / "bazel-testlogs").mkdir()

    result = _run_cli(tmp_path, "--yaml", "justifications.yaml", "--archive-dir", "artifacts")
    assert result.returncode == 0, result.stderr
    assert "references unknown ID 'itest-positive-branch'" in result.stderr
    report_json = tmp_path / "artifacts/justification_report/report.json"
    summary = json.loads(report_json.read_text(encoding="utf-8"))["summary"]
    assert summary["effective_line_coverage_pct"] == summary["raw_line_coverage_pct"]
