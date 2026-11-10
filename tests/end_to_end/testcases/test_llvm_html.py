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
"""Portable HTML coverage reports produced by the LLVM consumer pipeline."""

import re
from pathlib import Path
from zipfile import ZipFile

import pytest
from _blackbox_support import HtmlPage, run_bazel, verifies


@pytest.fixture(scope="module", name="html_directory")
def _html_directory(llvm_artifacts: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Inspect the same ZIP that CI publishes, unpacked away from the original output directory."""
    extracted = tmp_path_factory.mktemp("llvm_archive")
    with ZipFile(llvm_artifacts / "coverage_artifacts.zip") as archive:
        archive.extractall(extracted)
    return extracted / "artifacts/coverage_linux"


@pytest.fixture(scope="module", name="index")
def _index(html_directory: Path) -> HtmlPage:
    """Parse the shared index once for all HTML checks."""
    return HtmlPage((html_directory / "index.html").read_text(encoding="utf-8"))


@verifies(
    "tool_req__coverage_report_outputs", "tool_req__coverage_gate_threshold", "tool_req__coverage_gate_exit_codes"
)
def test_html_is_produced_without_justifications(consumer_with_llvm_coverage: Path, tmp_path: Path) -> None:
    """The raw gate passes at 10% and writes HTML without a YAML file."""
    output = tmp_path / "coverage"
    run_bazel(
        consumer_with_llvm_coverage,
        ["run", "@score_coverage//:generate_coverage_html", "--", str(output)],
        env={"COVERAGE_THRESHOLD": "10"},
    )
    assert (output / "index.html").is_file()


@verifies("tool_req__coverage_report_baseline_zero")
@pytest.mark.parametrize("source", ["src/uncovered.cpp", "src/main.cpp", "rust/main.rs"])
def test_untested_sources_show_zero_line_coverage(
    index: HtmlPage, llvm_lcov: dict[str, list[str]], source: str
) -> None:
    """The HTML line totals for untested sources agree with their validated LCOV records."""
    line_column = index.rows[0].index("Line Coverage")
    rows = [row for row in index.rows if row[0] == source]
    assert len(rows) == 1, f"Expected one index row for {source}, got {rows}"
    line_total = next(entry.removeprefix("LF:") for entry in llvm_lcov[source] if entry.startswith("LF:"))
    assert re.fullmatch(rf"0(?:\.0+)?%\s*\(0/{line_total}\)", rows[0][line_column])


@verifies("tool_req__coverage_report_relative_paths", "tool_req__coverage_artifacts")
def test_index_source_links_resolve_in_archived_report(index: HtmlPage, html_directory: Path) -> None:
    """Every source link opens a generated page within the portable report tree."""
    links = [link for link in index.links if link.startswith("coverage/")]
    assert links, "The index contains no source links"
    for link in links:
        assert (html_directory / link).is_file(), f"Missing source page: {link}"


@verifies("tool_req__coverage_report_relative_paths")
def test_index_source_links_use_canonical_lcov_paths(index: HtmlPage, llvm_lcov: dict[str, list[str]]) -> None:
    """Each source name links to its own canonical page in the archive."""
    source_links = [(label, href) for label, href in index.anchors if href.startswith("coverage/")]
    expected = [(source, f"coverage/{source}.html") for source in sorted(llvm_lcov)]
    assert sorted(source_links) == expected


@verifies("tool_req__coverage_report_relative_paths", "tool_req__coverage_artifacts")
def test_source_page_stylesheets_resolve_in_archived_report(index: HtmlPage, html_directory: Path) -> None:
    """Moving the HTML tree into the archive preserves each source page's stylesheet links."""
    links = [link for link in index.links if link.startswith("coverage/")]
    assert links, "The index contains no source links"
    for link in links:
        page = html_directory / link
        stylesheets = HtmlPage(page.read_text(encoding="utf-8")).stylesheets
        assert stylesheets, f"No stylesheet linked by {link}"
        for stylesheet in stylesheets:
            target = (page.parent / stylesheet).resolve()
            assert target.is_relative_to(html_directory.resolve()), f"Stylesheet points outside the report: {target}"
            assert target.is_file(), f"Broken stylesheet in {link}: {stylesheet}"


@verifies("tool_req__coverage_report_relative_paths")
@pytest.mark.parametrize(
    "source",
    ["src/vendored/include/vendored/inline_math.h", "external/itest_external+/include/vext/vext.h"],
    ids=["test-only-twin", "external-header"],
)
def test_vendored_headers_are_linked(index: HtmlPage, source: str) -> None:
    """The index links vendored headers under their declared paths."""
    assert f"coverage/{source}.html" in index.links


@verifies("tool_req__coverage_report_allowlist")
@pytest.mark.parametrize(
    "source", ["external/itest_external+/extlib.cpp", "external/itest_external+/include/extlib/extlib.h"]
)
def test_forwarded_third_party_sources_are_not_linked(index: HtmlPage, source: str) -> None:
    """The index excludes linked third-party code that is outside the coverage scope."""
    assert f"coverage/{source}.html" not in index.links
