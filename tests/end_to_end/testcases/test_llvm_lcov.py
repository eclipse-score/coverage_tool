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
"""Line and branch coverage reported by the LLVM consumer pipeline."""

from pathlib import Path

import pytest
from _blackbox_support import lcov_records, verifies


@verifies("tool_req__coverage_validation_ground_truth")
def test_llvm_lcov_matches_hand_derived_ground_truth(llvm_lcov: dict[str, list[str]]) -> None:
    """All line and branch entries match the fixture's hand-derived reference."""
    reference = Path(__file__).parent / "expected/expected_lcov.dat"
    assert llvm_lcov == lcov_records(reference.read_text(encoding="utf-8"))


@verifies("tool_req__coverage_report_baseline_zero")
@pytest.mark.parametrize("source", ["src/uncovered.cpp", "src/main.cpp", "rust/main.rs"])
def test_untested_sources_have_zero_line_hits(llvm_lcov: dict[str, list[str]], source: str) -> None:
    """Unlinked C++ library code and untested C++/Rust binaries still contribute zero-hit records."""
    assert "LH:0" in llvm_lcov[source]


@verifies("tool_req__coverage_report_merged_profile")
@pytest.mark.parametrize("source", ["src/coverable.cpp", "rust/lib.rs", "lib/cross_pkg.cpp"])
def test_tested_sources_have_line_hits(llvm_lcov: dict[str, list[str]], source: str) -> None:
    """Both languages and the library exercised from a test/ subpackage have measured hits."""
    assert any(line.startswith("DA:") and int(line.split(",")[1]) > 0 for line in llvm_lcov[source])


@verifies("tool_req__coverage_scope_platform")
@pytest.mark.parametrize(
    "selected, excluded",
    [
        ("src/platform_host.cpp", "src/platform_target.cpp"),
        ("src/host_root.cpp", "src/target_root.cpp"),
    ],
    ids=["library-source", "scope-root"],
)
def test_llvm_scope_uses_host_platform(llvm_lcov: dict[str, list[str]], selected: str, excluded: str) -> None:
    """The LLVM run selects host variants for library sources and scope dependencies."""
    assert selected in llvm_lcov
    assert excluded not in llvm_lcov


@verifies("tool_req__coverage_report_relative_paths")
@pytest.mark.parametrize(
    "source",
    [
        "src/vendored/include/vendored/inline_math.h",
        "external/itest_external+/include/vext/vext.h",
    ],
    ids=["test-only-twin", "external-header"],
)
def test_vendored_headers_use_declared_paths(llvm_lcov: dict[str, list[str]], source: str) -> None:
    """Headers compiled through strip_include_prefix are attributed to their declared source paths."""
    assert source in llvm_lcov


@verifies("tool_req__coverage_report_allowlist")
@pytest.mark.parametrize(
    "source", ["external/itest_external+/extlib.cpp", "external/itest_external+/include/extlib/extlib.h"]
)
def test_forwarded_third_party_sources_are_excluded(llvm_lcov: dict[str, list[str]], source: str) -> None:
    """Linked third-party code outside the coverage scope contributes no LCOV records."""
    assert source not in llvm_lcov


@verifies("tool_req__coverage_report_unmapped")
def test_uncompiled_header_has_no_invented_lcov_record(llvm_lcov: dict[str, list[str]]) -> None:
    """An unused template-only header has no measured or baseline coverage to report."""
    assert "src/unused_api.h" not in llvm_lcov
