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
"""Black-box scenarios for LLVM reports, artifacts, and source mapping."""

# Keep backend-specific command setup and expected artifacts visible in each
# module; pylint otherwise flags this intentional cross-backend test symmetry.
# pylint: disable=duplicate-code

import os
import re
import shutil
import zipfile
from pathlib import Path

import pytest
from _blackbox_support import (
    EXPECTED_UNMAPPED_LLVM,
    JUSTIFICATIONS,
    CoverageReport,
    assert_exit_code,
    generate_report,
    index_links,
    lcov_from_artifacts,
    lcov_records,
    line_counts,
    normalise_lcov,
    summary_metric,
    verifies,
)


@pytest.fixture(name="llvm_effective_archive", scope="module")
def create_llvm_effective_archive(llvm_report: CoverageReport, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate one effective-coverage archive for the artifact scenarios."""
    output_directory = os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR")
    output_root = Path(output_directory) if output_directory else tmp_path_factory.mktemp("llvm-archive")
    archive = output_root / "coverage_artifact"
    # Bazel may reuse its undeclared-output directory between runs.
    shutil.rmtree(archive, ignore_errors=True)
    result = generate_report(llvm_report, "--yaml", JUSTIFICATIONS, "--archive-dir", str(archive))
    assert_exit_code(result, 0)
    return archive


@pytest.fixture(name="llvm_raw_html_archive", scope="module")
def create_llvm_raw_html_archive(llvm_report: CoverageReport, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate raw-coverage HTML at 100%, where the coverage gate should fail."""
    archive = tmp_path_factory.mktemp("llvm-html") / "coverage-artifacts"
    result = generate_report(llvm_report, "--archive-dir", str(archive), threshold="100")
    assert_exit_code(result, 1)
    return archive


@pytest.fixture(
    name="llvm_html_archive",
    scope="module",
    params=["llvm_raw_html_archive", "llvm_effective_archive"],
    ids=["raw", "effective"],
)
def select_llvm_html_archive(request: pytest.FixtureRequest) -> Path:
    """Check both collected HTML and HTML rewritten by justification processing."""
    return request.getfixturevalue(request.param)


@pytest.mark.parametrize(
    ("threshold", "expected_exit"),
    [("100", 1), ("10", 0)],
    ids=["zip-written-on-failure", "zip-written-on-pass"],
)
@verifies("tool_req__coverage_artifacts")
def test_llvm_zip_contains_reports_and_consumer_test_results(
    llvm_report: CoverageReport,
    llvm_effective_archive: Path,
    tmp_path: Path,
    threshold: str,
    expected_exit: int,
) -> None:
    """A ZIP preserves the artifacts layout and data even when the gate fails."""
    archive_name = tmp_path / "coverage-artifacts"
    result = generate_report(llvm_report, "--yaml", JUSTIFICATIONS, "--archive", str(archive_name), threshold=threshold)
    assert_exit_code(result, expected_exit)
    with zipfile.ZipFile(archive_name.with_suffix(".zip")) as archive:
        members = set(archive.namelist())
        for relative_path in (
            "coverage_linux/index.html",
            "coverage_report.dat",
            "justification_report/summary.txt",
            "unmapped_files.txt",
        ):
            member = f"artifacts/{relative_path}"
            assert member in members, f"ZIP is missing {member}"
            assert archive.read(member) == (llvm_effective_archive / relative_path).read_bytes()
        # Source pages and their stylesheets must survive packaging, not just
        # the index that points to them.
        for page in (llvm_effective_archive / "coverage_linux").rglob("*"):
            if page.is_file():
                member = f"artifacts/{page.relative_to(llvm_effective_archive).as_posix()}"
                assert member in members, f"ZIP is missing HTML asset {member}"
                assert archive.read(member) == page.read_bytes()
        test_results = list((llvm_report.workspace / "bazel-testlogs").rglob("test.xml"))
        assert test_results, "consumer coverage collection must produce test results to archive"
        for test_result in test_results:
            member = f"artifacts/{test_result.relative_to(llvm_report.workspace).as_posix()}"
            assert member in members, f"ZIP is missing consumer test result {member}"
            assert archive.read(member) == test_result.read_bytes()


@verifies("tool_req__coverage_artifacts")
def test_effective_archive_contains_html_lcov_and_justification_summary(llvm_effective_archive: Path) -> None:
    """The consumer archive contains its HTML report, LCOV data, and justification summary."""
    assert (llvm_effective_archive / "coverage_linux" / "index.html").is_file()
    assert (llvm_effective_archive / "coverage_report.dat").is_file()
    assert (llvm_effective_archive / "justification_report" / "summary.txt").is_file()


@verifies("tool_req__coverage_report_unmapped")
def test_effective_archive_lists_unmapped_files(llvm_effective_archive: Path) -> None:
    """The archive categorizes every file omitted from the LLVM LCOV report."""
    unmapped = (llvm_effective_archive / "unmapped_files.txt").read_text(encoding="utf-8")
    assert unmapped == EXPECTED_UNMAPPED_LLVM


@verifies("tool_req__coverage_just_markers")
def test_effective_summary_credits_reviewed_justifications(llvm_effective_archive: Path) -> None:
    """Reviewed markers raise effective coverage above raw coverage."""
    summary_path = llvm_effective_archive / "justification_report" / "summary.txt"
    summary = summary_path.read_text(encoding="utf-8")
    raw_coverage = summary_metric(summary, "Raw line coverage")
    effective_coverage = summary_metric(summary, "Effective line coverage")

    assert re.search(r"Justified lines:\s+[1-9][0-9]*", summary)
    assert effective_coverage > raw_coverage


@verifies("tool_req__coverage_validation_ground_truth")
def test_llvm_report_matches_hand_derived_lcov_golden(
    llvm_report: CoverageReport, llvm_effective_archive: Path
) -> None:
    """The public archive matches the hand-derived C++ and Rust LCOV golden."""
    actual = normalise_lcov(lcov_from_artifacts(llvm_effective_archive))
    golden_path = llvm_report.workspace.parent / "expected" / "expected_lcov.dat"
    expected = normalise_lcov(golden_path.read_text(encoding="utf-8"))

    assert actual == expected


@verifies("tool_req__coverage_report_baseline_zero")
def test_lcov_keeps_zero_hit_records_for_uncovered_cpp_and_rust(llvm_effective_archive: Path) -> None:
    """Uncovered C++ and Rust sources remain present as zero-hit LCOV records."""
    records = lcov_records(lcov_from_artifacts(llvm_effective_archive))
    for source in ("src/uncovered.cpp", "rust/main.rs"):
        counts = line_counts(records, source)
        assert counts.found > 0, f"{source} has no executable lines in the LCOV report"
        assert counts.hits == 0, f"{source} should have zero covered lines"


@verifies("tool_req__coverage_report_unmapped")
def test_uncompiled_header_is_listed_without_an_lcov_record(llvm_effective_archive: Path) -> None:
    """An in-scope header that was never compiled is reported separately from LCOV."""
    records = lcov_records(lcov_from_artifacts(llvm_effective_archive))
    unmapped = (llvm_effective_archive / "unmapped_files.txt").read_text(encoding="utf-8")

    assert "src/unused_api.h" not in records
    assert "no-data\tsrc/unused_api.h" in unmapped


@verifies("tool_req__coverage_report_relative_paths")
def test_html_links_resolve_to_generated_pages(llvm_html_archive: Path) -> None:
    """Every link in the HTML index points to a generated report page."""
    html_root = llvm_html_archive / "coverage_linux"
    links = index_links(html_root / "index.html")
    assert links

    for link in links:
        assert (html_root / link).is_file(), f"report page does not exist: {link}"


@verifies("tool_req__coverage_report_relative_paths")
def test_html_links_contain_no_machine_specific_paths(llvm_html_archive: Path) -> None:
    """Generated links stay workspace-relative instead of exposing local paths."""
    html_root = llvm_html_archive / "coverage_linux"
    links = index_links(html_root / "index.html")
    assert links

    machine_specific_paths = ("bazel-out", "_virtual_includes", "/home/", "/tmp/")
    for link in links:
        for path_fragment in machine_specific_paths:
            assert path_fragment not in link, f"report link contains {path_fragment}: {link}"


@verifies("tool_req__coverage_report_allowlist")
def test_html_includes_declared_external_and_vendored_headers(llvm_html_archive: Path) -> None:
    """The source allowlist includes declared external and vendored headers."""
    html_root = llvm_html_archive / "coverage_linux"
    links = index_links(html_root / "index.html")
    external_header = "coverage/external/itest_external+/include/vext/vext.h.html"
    vendored_header = "coverage/src/vendored/include/vendored/inline_math.h.html"
    assert external_header in links, f"missing external header page: {links}"
    assert vendored_header in links, f"missing vendored header page: {links}"


@verifies("tool_req__coverage_report_allowlist")
def test_html_excludes_forwarded_external_library(llvm_html_archive: Path) -> None:
    """Forwarded external library code is absent from the HTML and LCOV outputs."""
    html_root = llvm_html_archive / "coverage_linux"
    index = (html_root / "index.html").read_text(encoding="utf-8")
    lcov = lcov_from_artifacts(llvm_html_archive)

    assert "itest_external+/extlib" not in index
    assert "extlib" not in lcov


@verifies("tool_req__coverage_report_relative_paths")
def test_html_pages_link_to_existing_stylesheets(llvm_html_archive: Path) -> None:
    """Every HTML source page links to a stylesheet that exists beside it."""
    html_root = llvm_html_archive / "coverage_linux"
    links = index_links(html_root / "index.html")

    for link in links:
        page = html_root / link
        stylesheet = re.search(
            r"href=['\"]((?:\.\./)*style\.css)['\"]",
            page.read_text(encoding="utf-8"),
        )
        assert stylesheet, f"{link} does not reference its stylesheet"
        assert (page.parent / stylesheet.group(1)).is_file(), f"{link} stylesheet does not resolve"


@verifies("tool_req__coverage_scope_platform")
def test_llvm_report_selects_host_platform_sources(llvm_effective_archive: Path) -> None:
    """Without a target override, the LLVM scope follows the host platform."""
    records = lcov_records(lcov_from_artifacts(llvm_effective_archive))
    assert "src/platform_host.cpp" in records
    assert "src/host_root.cpp" in records
    assert "src/platform_target.cpp" not in records
    assert "src/target_root.cpp" not in records
