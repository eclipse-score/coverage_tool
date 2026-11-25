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

"""Validate C++ coverage counts, scope and merging through both production reporters.

Collect three reports per compiler/target configuration: test_a, test_b and their combined report.
C++ CHECK comments supply the hand-derived counter expectations. Scope and
cross-report relationships remain ordinary pytest assertions, independently
of the annotation reader and of the reporter's own implementation.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

import pytest
from _blackbox_support import lcov_records, run_bazel, verifies
from coverage_checks import CoverageCheck, execution_counters, parse_coverage_checks

LcovRecords = dict[str, list[str]]
ReportsByTestRun = dict[str, LcovRecords]


@dataclass(frozen=True)
class CoverageConfiguration:
    """Keep compiler/target selection separate from the reporter's data format."""

    backend: str
    bazel_config: str
    reporter: str


_CONFIGURATIONS = {
    "clang_linux": CoverageConfiguration("llvm", "llvm_cov", "reporter_llvm"),
    "gcc_linux": CoverageConfiguration("gcov", "gcov", "reporter_gcov"),
}
if os.environ.get("SCORE_COVERAGE_QNX") == "1":
    _CONFIGURATIONS["qcc_qnx"] = CoverageConfiguration("gcov", "qnx", "reporter_qnx")

_TEST_RUNS = {
    "test_a": ["//cpp_semantics:test_a"],
    "test_b": ["//cpp_semantics:test_b"],
    "combined_tests": ["//cpp_semantics:test_a", "//cpp_semantics:test_b"],
}
_ANNOTATED_SOURCES = (
    "cpp_semantics/inline_and_templates.h",
    "cpp_semantics/exception_paths.cpp",
)


def _read_scenario_checks() -> list[CoverageCheck]:
    """Load expectations during collection so each CHECK becomes a named pytest case."""
    # Collection precedes fixtures. Resolve symlinked runfiles the same way as
    # example_project does, then leave all Bazel execution to that fixture.
    example_project = Path(__file__).resolve().parents[1] / "example_project"
    checks = []
    for source in _ANNOTATED_SOURCES:
        checks.extend(parse_coverage_checks(source, (example_project / source).read_text(encoding="utf-8")))
    unknown_runs = {check.test_run for check in checks} - _TEST_RUNS.keys()
    if unknown_runs:
        raise ValueError(f"C++ CHECKs reference undefined test runs: {sorted(unknown_runs)}")
    return checks


_SCENARIO_CHECKS = _read_scenario_checks()
_BRANCH_LOCATIONS = sorted({(check.source, check.line) for check in _SCENARIO_CHECKS if check.metric == "branch_hits"})


# indirect=True sends each parameter through this fixture. Module scope keeps
# the three reports shared across all assertions for that compiler/target.
@pytest.fixture(scope="module", name="configuration")
def _configuration(request: pytest.FixtureRequest) -> str:
    """Select one compiler/target for a module-scoped batch of report checks."""
    return request.param


@pytest.fixture(scope="module", name="coverage_reports")
def _coverage_reports(example_project: Path, configuration: str) -> ReportsByTestRun:
    """Collect three snapshots once per selected configuration, shared by its assertions."""
    config = _CONFIGURATIONS[configuration]
    report_path = example_project / "bazel-out/_coverage/_coverage_report.dat"
    reports = {}
    for test_run, targets in _TEST_RUNS.items():
        # A successful Bazel exit can leave no new report, for example if
        # test filtering selects nothing. Every snapshot must come from its
        # own invocation, especially when the previous run used another OS.
        report_path.unlink(missing_ok=True)
        result = run_bazel(
            example_project,
            [
                "coverage",
                f"--config={config.bazel_config}",
                f"--coverage_report_generator=//cpp_semantics:{config.reporter}",
                "--instrumentation_filter=^//cpp_semantics[/:]",
                *targets,
            ],
        )
        assert report_path.is_file(), (
            f"{configuration}/{test_run}: Bazel did not produce a coverage report\n{result.stdout}\n{result.stderr}"
        )
        with ZipFile(report_path) as archive:
            report_text = archive.read("lcov_report/lcov.dat").decode("utf-8")
        reports[test_run] = lcov_records(report_text)
        if outputs := os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR"):
            (Path(outputs) / f"cpp_{configuration}_{test_run}.lcov").write_text(report_text, encoding="utf-8")
    return reports


def _branch_hit_counts(records: list[str], line: int, context: str) -> list[int]:
    """Require measured branch counters; absence and unknown hits are not measured zeros."""
    prefix = f"BRDA:{line},"
    counts = [entry.rsplit(",", 1)[1] for entry in records if entry.startswith(prefix)]
    assert counts, f"{context}: missing branch counters"
    assert "-" not in counts, f"{context}: expected measured branch hits, got {counts}"
    return [int(count) for count in counts]


@verifies("tool_req__coverage_validation_ground_truth")
@pytest.mark.parametrize("configuration", _CONFIGURATIONS, indirect=True)
@pytest.mark.parametrize("check", _SCENARIO_CHECKS, ids=lambda check: check.test_id)
def test_annotated_counter_matches_expected_hits(
    coverage_reports: ReportsByTestRun,
    configuration: str,
    check: CoverageCheck,
    request: pytest.FixtureRequest,
) -> None:
    """One C++ CHECK asserts one line count or branch-hit sum in one test run's report."""
    records = coverage_reports[check.test_run][check.source]
    context = f"{check.source}:{check.line} [{configuration}/{check.test_run}]"
    if check.metric == "line_hits":
        prefix = f"DA:{check.line},"
        counts = [int(entry.split(",")[1]) for entry in records if entry.startswith(prefix)]
        assert len(counts) == 1, f"{context}: expected one line counter, got {counts}"
        actual = counts[0]
    else:
        actual = sum(_branch_hit_counts(records, check.line, context))
    # Apply XFAIL only after validating the counter's presence. A documented
    # backend count discrepancy must not hide missing coverage data.
    if check.xfail_backend == _CONFIGURATIONS[configuration].backend:
        request.applymarker(
            pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="Backend discrepancy documented beside the C++ CHECK",
            )
        )
    assert actual == check.expected_hits, f"{context}: expected {check.metric} == {check.expected_hits}, got {actual}"


@verifies("tool_req__coverage_validation_ground_truth")
@pytest.mark.parametrize("configuration", _CONFIGURATIONS, indirect=True)
@pytest.mark.parametrize(
    "source,line", _BRANCH_LOCATIONS, ids=[f"{source}:{line}" for source, line in _BRANCH_LOCATIONS]
)
def test_complementary_tests_cover_both_branch_outcomes(
    coverage_reports: ReportsByTestRun, configuration: str, source: str, line: int
) -> None:
    """Each individual test leaves an edge uncovered; together they cover every instance's edges."""
    for test_run in _TEST_RUNS:
        context = f"{source}:{line} [{configuration}/{test_run}]"
        counts = _branch_hit_counts(coverage_reports[test_run][source], line, context)
        if test_run == "combined_tests":
            assert all(count > 0 for count in counts), f"{context}: uncovered branch in {counts}"
        else:
            assert 0 in counts, f"{context}: expected an uncovered branch in {counts}"


@verifies("tool_req__coverage_report_allowlist")
@pytest.mark.parametrize("configuration", _CONFIGURATIONS, indirect=True)
def test_combined_report_contains_exactly_the_declared_scope(
    coverage_reports: ReportsByTestRun, configuration: str, request: pytest.FixtureRequest
) -> None:
    """Library sources and headers are in scope; the linked main.cpp is excluded."""
    actual = set(coverage_reports["combined_tests"])
    expected = {
        "cpp_semantics/inline_and_templates.h",
        "cpp_semantics/int_template_caller.cpp",
        "cpp_semantics/mixed_template_caller.cpp",
        "cpp_semantics/exception_paths.cpp",
    }
    # LLVM's filename discovery loses the shared directory prefix, allowing
    # the linked driver through scope filtering. Accept only this exact known
    # discrepancy: missing library files or other extra files must still fail.
    # https://github.com/eclipse-score/coverage_tool/issues/70
    if configuration == "clang_linux":
        assert actual in (expected, expected | {"cpp_semantics/main.cpp"})
        request.applymarker(
            pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="LLVM scope includes the test driver: https://github.com/eclipse-score/coverage_tool/issues/70",
            )
        )
    assert actual == expected


def _assert_counter_summation(reports: ReportsByTestRun) -> None:
    """Every measured line/branch must survive merging with its execution counts added."""
    run_a, run_b, combined = (reports[test_run] for test_run in ("test_a", "test_b", "combined_tests"))
    assert run_a.keys() == run_b.keys() == combined.keys(), "Source records differ between test runs"
    for source in combined:
        counters_a = execution_counters(run_a[source])
        counters_b = execution_counters(run_b[source])
        merged_counters = execution_counters(combined[source])
        assert counters_a.keys() == counters_b.keys() == merged_counters.keys(), f"{source}: counter identities differ"
        for counter, actual in merged_counters.items():
            individual_counts = [counters_a[counter], counters_b[counter]]
            # gcov's unknown '-' remains unknown only when neither test has a
            # measured count. Once either test measures it, sum the known hits.
            expected = (
                "-"
                if individual_counts == ["-", "-"]
                else str(sum(int(hit) for hit in individual_counts if hit != "-"))
            )
            assert actual == expected, f"{source} {counter}: expected merged hits {expected}, got {actual}"


@verifies("tool_req__coverage_validation_ground_truth", "tool_req__coverage_report_merged_profile")
@pytest.mark.parametrize(
    "configuration",
    [name for name, config in _CONFIGURATIONS.items() if config.backend == "llvm"],
    indirect=True,
)
def test_llvm_merged_profile_preserves_counter_sums(coverage_reports: ReportsByTestRun) -> None:
    """Merged LLVM profiles produce the sum of both tests' line and branch execution counts."""
    _assert_counter_summation(coverage_reports)


@verifies("tool_req__coverage_validation_ground_truth", "tool_req__coverage_gcov_merge")
@pytest.mark.parametrize(
    "configuration",
    [name for name, config in _CONFIGURATIONS.items() if config.backend == "gcov"],
    indirect=True,
)
def test_gcov_merged_records_preserve_counter_sums(coverage_reports: ReportsByTestRun) -> None:
    """Merged gcov records sum measured counts and preserve branches unknown in both tests."""
    _assert_counter_summation(coverage_reports)
