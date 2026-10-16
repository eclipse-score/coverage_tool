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
"""Markdown summaries produced by the public CLI against LLVM consumer coverage."""

import re
from pathlib import Path

from _blackbox_support import run_bazel, verifies

_JUSTIFICATIONS = "tools/coverage/coverage_justifications.yaml"


@verifies("tool_req__coverage_summary_first")
def test_markdown_summary_contains_coverage_and_source_categories(
    consumer_with_llvm_coverage: Path, tmp_path: Path
) -> None:
    """The LLVM summary includes metrics, progress bars and each unmapped-source category."""
    summary = tmp_path / "summary.md"
    run_bazel(
        consumer_with_llvm_coverage,
        [
            "run",
            "@score_coverage//:generate_coverage_html",
            "--",
            "--yaml",
            _JUSTIFICATIONS,
            "--summary-md",
            str(summary),
        ],
        env={"COVERAGE_THRESHOLD": "10"},
    )
    content = summary.read_text(encoding="utf-8")
    markers = (
        "## Coverage summary",
        "| Lines |",
        "Raw vs effective",
        "Coverage by directory",
        "Files at exact 0% (4)",  # uncovered.cpp, host_root.cpp, main.cpp, rust/main.rs
        "- `src/main.cpp`",
        "| In-scope files without coverage data | 2 |",
        "In-scope files without coverage data (2)",
        "- `src/unused_api.h`",
        "- `src/platform_dep.h`",
        "Declaration-only headers (3)",
        "Compiled sources without code of their own (1)",
        "- `src/empty_unit.cpp`",
        "█",
    )
    for marker in markers:
        assert marker in content, f"Summary is missing {marker!r}"


@verifies("tool_req__coverage_summary_first", "tool_req__coverage_gate_exit_codes")
def test_markdown_summary_is_written_when_gate_fails(consumer_with_llvm_coverage: Path, tmp_path: Path) -> None:
    """Measured effective coverage below the required 100% fails the gate and still produces a summary."""
    summary = tmp_path / "summary.md"
    result = run_bazel(
        consumer_with_llvm_coverage,
        [
            "run",
            "@score_coverage//:generate_coverage_html",
            "--",
            "--yaml",
            _JUSTIFICATIONS,
            "--summary-md",
            str(summary),
        ],
        expected_exit_code=1,
        env={"COVERAGE_THRESHOLD": "100"},
    )
    gate_failure = re.search(r"ERROR: Effective coverage (\d+(?:\.\d+)?)% is below threshold 100%", result.stderr)
    assert gate_failure is not None, result.stderr
    assert 0 < float(gate_failure.group(1)) < 100
    content = summary.read_text(encoding="utf-8")
    assert "## Coverage summary" in content
    assert "| Lines |" in content
    assert "Raw vs effective" in content


@verifies("tool_req__coverage_summary_first")
def test_github_step_summary_appends_without_explicit_flag(consumer_with_llvm_coverage: Path, tmp_path: Path) -> None:
    """The environment-selected summary retains content from an earlier CI step."""
    summary = tmp_path / "step_summary.md"
    earlier_content = "# existing content\n"
    summary.write_text(earlier_content, encoding="utf-8")
    run_bazel(
        consumer_with_llvm_coverage,
        ["run", "@score_coverage//:generate_coverage_html", "--", "--yaml", _JUSTIFICATIONS],
        env={"COVERAGE_THRESHOLD": "10", "GITHUB_STEP_SUMMARY": str(summary)},
    )
    content = summary.read_text(encoding="utf-8")
    assert content.startswith(earlier_content)
    assert "## Coverage summary" in content
