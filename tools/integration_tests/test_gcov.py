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
"""Black-box scenarios for the gcov coverage backend."""

import re
import zipfile
from pathlib import Path

import pytest
from _blackbox_support import (
    EXPECTED_UNMAPPED_GCOV,
    JUSTIFICATIONS,
    CoverageReport,
    assert_exit_code,
    collect_report,
    generate_report,
    lcov_from_artifacts,
    lcov_records,
    line_counts,
    normalise_lcov,
    summary_metric,
    verifies,
)


@pytest.fixture(name="gcov_lcov_archive", scope="module")
def create_gcov_lcov_archive(gcov_report: CoverageReport, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate the gcov LCOV archive used by the golden-report scenarios."""
    archive = tmp_path_factory.mktemp("gcov-lcov") / "coverage-artifacts"
    result = generate_report(gcov_report, "--yaml", JUSTIFICATIONS, "--archive-dir", str(archive))
    assert_exit_code(result, 0)
    return archive


@pytest.fixture(name="gcov_html_archive", scope="module")
def create_gcov_html_archive(gcov_report: CoverageReport, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate gcov HTML and its Markdown summary for the archive scenarios."""
    output_root = tmp_path_factory.mktemp("gcov-html")
    archive = output_root / "coverage-artifacts"
    markdown_summary = output_root / "gcov-summary.md"
    result = generate_report(
        gcov_report,
        "--yaml",
        JUSTIFICATIONS,
        "--archive-dir",
        str(archive),
        "--summary-md",
        str(markdown_summary),
        "coverage_gcov",
    )
    assert_exit_code(result, 0)
    return archive


@pytest.mark.parametrize(
    ("threshold", "expected_exit"),
    [("100", 1), ("10", 0)],
    ids=["fails-at-100-percent", "passes-at-10-percent"],
)
@verifies("tool_req__coverage_gate_exit_codes", derivation="boundary-values")
def test_gcov_effective_gate_uses_reviewed_justifications(
    gcov_report: CoverageReport, threshold: str, expected_exit: int
) -> None:
    """Reviewed justifications make the gcov 10% gate pass and 100% gate fail."""
    result = generate_report(gcov_report, "--yaml", JUSTIFICATIONS, threshold=threshold)
    assert_exit_code(result, expected_exit)


@verifies("tool_req__coverage_validation_ground_truth")
def test_gcov_lcov_matches_hand_derived_golden(gcov_report: CoverageReport, gcov_lcov_archive: Path) -> None:
    """The generated gcov LCOV report matches its hand-derived golden."""
    actual = normalise_lcov(lcov_from_artifacts(gcov_lcov_archive))
    golden_path = gcov_report.workspace / "expected_lcov_gcov.dat"
    expected = normalise_lcov(golden_path.read_text(encoding="utf-8"))

    assert actual == expected


@verifies("tool_req__coverage_gcov_merge", "tool_req__coverage_gcov_baseline")
def test_gcov_lcov_measures_vendored_header(gcov_lcov_archive: Path) -> None:
    """The gcov LCOV report includes hits from the vendored C++ header."""
    records = lcov_records(lcov_from_artifacts(gcov_lcov_archive))
    header = "external/itest_external+/include/vext/vext.h"

    assert line_counts(records, header).hits > 0


@verifies("tool_req__coverage_gcov_merge")
def test_gcov_lcov_omits_rust_sources(gcov_lcov_archive: Path) -> None:
    """The gcov LCOV report contains no Rust source records."""
    records = lcov_records(lcov_from_artifacts(gcov_lcov_archive))
    assert not any(path.endswith(".rs") for path in records)


@verifies("tool_req__coverage_gcov_html")
def test_gcov_html_links_resolve_to_generated_pages(gcov_html_archive: Path) -> None:
    """Every linked gcov HTML page exists in the consumer archive."""
    html_root = gcov_html_archive / "coverage_gcov"
    index = (html_root / "index.html").read_text(encoding="utf-8")
    page_links = re.findall(r'href="(index\.[^"]+\.html)"', index)
    assert page_links

    for link in page_links:
        assert (html_root / link).is_file(), f"gcov report page does not exist: {link}"


@verifies("tool_req__coverage_just_markers")
def test_gcov_summary_credits_reviewed_justifications(gcov_html_archive: Path) -> None:
    """The gcov justification summary reports higher effective than raw coverage."""
    summary_path = gcov_html_archive / "justification_report" / "summary.txt"
    summary = summary_path.read_text(encoding="utf-8")
    raw_coverage = summary_metric(summary, "Raw line coverage")
    effective_coverage = summary_metric(summary, "Effective line coverage")

    assert effective_coverage > raw_coverage


@verifies("tool_req__coverage_report_unmapped")
def test_gcov_archive_lists_unmapped_files(gcov_html_archive: Path) -> None:
    """The gcov archive categorizes every source omitted from its report."""
    unmapped = (gcov_html_archive / "unmapped_files.txt").read_text(encoding="utf-8")
    assert unmapped == EXPECTED_UNMAPPED_GCOV


@verifies("tool_req__coverage_report_unmapped")
def test_gcov_markdown_summary_explains_uninstrumented_rust(gcov_html_archive: Path) -> None:
    """The Markdown summary explains that gcov cannot instrument the Rust files."""
    markdown_path = gcov_html_archive.parent / "gcov-summary.md"
    markdown_summary = markdown_path.read_text(encoding="utf-8")
    assert "Not instrumentable by this backend (2)" in markdown_summary


@verifies("tool_req__coverage_instrumentation_hint", derivation="error-guessing")
def test_gcov_narrow_filter_warns_and_leaves_excluded_library_at_zero(consumer_workspace: Path, tmp_path: Path) -> None:
    """A narrowed instrumentation filter warns and leaves the omitted library at zero hits."""
    # This config builds both packages but instruments only //src/ and //lib/test/.
    report = collect_report(
        consumer_workspace,
        "gcov",
        ["//src/...", "//lib/..."],
        tmp_path / "gcov-narrow-filter.dat",
        extra_args=["--config=gcov_narrow_filter"],
    )
    output = report.collection_output

    assert "in-scope files have no test data" in output
    assert "WARNING: 1 in-scope files have no test data" in output
    assert "--instrumentation_filter=^//<root package>[/:]" in output

    with zipfile.ZipFile(report.archive) as archive:
        lcov_member = next(name for name in archive.namelist() if name.endswith("lcov_report/lcov.dat"))
        records = lcov_records(archive.read(lcov_member).decode("utf-8"))
    assert line_counts(records, "lib/cross_pkg.cpp").hits == 0
