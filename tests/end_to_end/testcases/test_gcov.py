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
"""End-to-end validation of the GCC coverage pipeline."""

import json
from pathlib import Path
from subprocess import CompletedProcess
from typing import NamedTuple
from zipfile import ZipFile

import pytest
from _blackbox_support import EXPECTED_CPP_UNMAPPED, HtmlPage, lcov_records, run_bazel, verifies

_COVERAGE_ARGS = ["coverage", "--config=gcov", "//src/...", "//lib/...", "--build_tests_only"]
_JUSTIFICATIONS = "tools/coverage/coverage_justifications.yaml"


class GcovOutputs(NamedTuple):
    """Artifacts and gate result from the fully instrumented run."""

    directory: Path
    rejected_gate: CompletedProcess[str]


@pytest.fixture(scope="module", name="gcov_outputs")
def _gcov_outputs(consumer_workspace: Path, tmp_path_factory: pytest.TempPathFactory) -> GcovOutputs:
    """Build once and snapshot the outputs before another coverage command can replace the report."""
    run_bazel(consumer_workspace, _COVERAGE_ARGS)
    output = tmp_path_factory.mktemp("gcov")
    cli = ["run", "@score_coverage//:generate_coverage_html", "--", "--yaml", _JUSTIFICATIONS]
    rejected_gate = run_bazel(
        consumer_workspace,
        [*cli, str(output / "rejected")],
        expected_exit_code=1,
        env={"COVERAGE_THRESHOLD": "100"},
    )
    run_bazel(
        consumer_workspace,
        [
            *cli,
            "--archive-dir",
            str(output / "artifacts"),
            "--summary-md",
            str(output / "summary.md"),
            str(output / "coverage_gcov"),
        ],
        env={"COVERAGE_THRESHOLD": "10"},
    )
    return GcovOutputs(output, rejected_gate)


@pytest.fixture(scope="module", name="gcov_lcov")
def _gcov_lcov(gcov_outputs: GcovOutputs) -> dict[str, list[str]]:
    """Read the archived records, independent of subsequent Bazel invocations."""
    return lcov_records((gcov_outputs.directory / "artifacts/coverage_report.dat").read_text(encoding="utf-8"))


@verifies("tool_req__coverage_gate_exit_codes")
def test_gcov_gate_fails_at_high_threshold(gcov_outputs: GcovOutputs) -> None:
    """The high threshold yields an effective-coverage rejection."""
    assert "Effective coverage" in gcov_outputs.rejected_gate.stderr
    assert "below threshold 100%" in gcov_outputs.rejected_gate.stderr


@verifies("tool_req__coverage_validation_ground_truth", "tool_req__coverage_artifacts")
def test_archived_gcov_matches_hand_derived_ground_truth(gcov_lcov: dict[str, list[str]]) -> None:
    """Compare all measured line and branch entries from the low-threshold run."""
    reference = Path(__file__).parent / "expected/expected_lcov_gcov.dat"
    assert gcov_lcov == lcov_records(reference.read_text(encoding="utf-8"))


@verifies("tool_req__coverage_gcov_html", "tool_req__coverage_artifacts")
def test_archived_gcov_index_links_to_source_pages(gcov_outputs: GcovOutputs) -> None:
    """The archived index opens source pages for tested and baseline sources."""
    html = gcov_outputs.directory / "artifacts/coverage_gcov"
    index = HtmlPage((html / "index.html").read_text(encoding="utf-8"))
    links = {link for link in index.links if link.startswith("index.") and link.endswith(".html")}
    for source in (
        "coverable.cpp",
        "uncovered.cpp",
        "inline_math.h",
        "cross_pkg.cpp",
        "platform_target.cpp",
        "target_root.cpp",
    ):
        assert any(link.startswith(f"index.{source}.") for link in links), f"No indexed source page for {source}"
    for link in links:
        assert (html / link).is_file(), f"Broken source link: {link}"


@verifies("tool_req__coverage_eff_gcovr")
def test_gcov_justifications_raise_effective_coverage(gcov_outputs: GcovOutputs) -> None:
    """The marked uncovered line raises effective coverage for the gcovr report."""
    report = gcov_outputs.directory / "artifacts/justification_report/report.json"
    summary = json.loads(report.read_text(encoding="utf-8"))["summary"]
    assert summary["effective_line_coverage_pct"] > summary["raw_line_coverage_pct"]


@verifies("tool_req__coverage_report_unmapped")
def test_archived_gcov_unmapped_sources_are_classified(gcov_outputs: GcovOutputs) -> None:
    """The gcov archive lists all unmapped findings, including the Rust sources GCC cannot measure."""
    records = (gcov_outputs.directory / "artifacts/unmapped_files.txt").read_text(encoding="utf-8").splitlines()
    expected = (*EXPECTED_CPP_UNMAPPED, "not-instrumented\trust/lib.rs", "not-instrumented\trust/main.rs")
    assert sorted(records) == sorted(expected)


@verifies("tool_req__coverage_summary_first")
def test_gcov_summary_lists_sources_the_backend_cannot_measure(gcov_outputs: GcovOutputs) -> None:
    """Rust sources appear under the summary category for unsupported instrumentation."""
    summary = (gcov_outputs.directory / "summary.md").read_text(encoding="utf-8")
    _, section, following = summary.partition("<summary>Not instrumentable by this backend")
    assert section
    section_body = following.partition("</details>")[0]
    assert "`rust/lib.rs`" in section_body
    assert "`rust/main.rs`" in section_body


@verifies("tool_req__coverage_scope_platform")
@pytest.mark.parametrize(
    "selected, excluded",
    [("src/platform_target.cpp", "src/platform_host.cpp"), ("src/target_root.cpp", "src/host_root.cpp")],
    ids=["library-source", "scope-root"],
)
def test_gcov_scope_uses_target_platform(gcov_lcov: dict[str, list[str]], selected: str, excluded: str) -> None:
    """Library and root selections follow the target platform of the coverage run."""
    assert selected in gcov_lcov
    assert excluded not in gcov_lcov


@verifies("tool_req__coverage_instrumentation_hint", "tool_req__coverage_gcov_baseline")
def test_gcov_warns_when_instrumentation_misses_library(consumer_workspace: Path) -> None:
    """The guessed filter drops the cross-package library's counters and leaves its zero-hit baseline."""
    result = run_bazel(
        consumer_workspace,
        [*_COVERAGE_ARGS, "--instrumentation_filter=^//lib/test[/:],^//src[/:]"],
    )
    output = result.stdout + result.stderr
    assert "have no test data although their directory is tested" in output
    assert "--instrumentation_filter=^//<root package>[/:]" in output
    assert "lib/cross_pkg.cpp" in output
    with ZipFile(consumer_workspace / "bazel-out/_coverage/_coverage_report.dat") as report:
        records = lcov_records(report.read("lcov_report/lcov.dat").decode("utf-8"))
    assert "LH:0" in records["lib/cross_pkg.cpp"]
