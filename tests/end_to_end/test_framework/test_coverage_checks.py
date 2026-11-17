# Copyright (c) 2026 Contributors to the Eclipse Foundation
#
# SPDX-License-Identifier: Apache-2.0

"""Validate the annotation reader independently of Bazel, compilers and coverage reports."""

import pytest
from coverage_checks import CoverageCheck, parse_coverage_checks


def test_checks_skip_explanations_blank_lines_and_block_comments() -> None:
    """Explanations between expectations do not change the code line they refer to."""
    text = "\n".join(
        [
            "// CHECK test_a: line_hits == 1",
            "// test_a reaches the return once.",
            "",
            "/* More explanation",
            "   continued on another line. */",
            "// CHECK combined_tests: line_hits == 2",
            "return value;",
        ]
    )
    assert parse_coverage_checks("fixture.cpp", text) == [
        CoverageCheck("fixture.cpp", 7, "test_a", "line_hits", 1),
        CoverageCheck("fixture.cpp", 7, "combined_tests", "line_hits", 2),
    ]


def test_checks_are_consumed_by_exactly_one_code_line() -> None:
    """A later CHECK belongs to its own following code line, never the preceding one."""
    text = "\n".join(
        [
            "// CHECK test_a: line_hits == 1",
            "first();",
            "// CHECK test_a: line_hits == 2",
            "second();",
        ]
    )
    assert parse_coverage_checks("fixture.cpp", text) == [
        CoverageCheck("fixture.cpp", 2, "test_a", "line_hits", 1),
        CoverageCheck("fixture.cpp", 4, "test_a", "line_hits", 2),
    ]


def test_one_code_line_can_have_both_line_and_branch_expectations() -> None:
    """Different metrics for the same test run are distinct assertions on the same line."""
    text = "\n".join(
        [
            "// CHECK test_a: line_hits == 2",
            "// CHECK test_a: branch_hits == 2",
            "if (value < 0) {",
        ]
    )
    assert parse_coverage_checks("fixture.cpp", text) == [
        CoverageCheck("fixture.cpp", 3, "test_a", "line_hits", 2),
        CoverageCheck("fixture.cpp", 3, "test_a", "branch_hits", 2),
    ]


def test_expected_failure_applies_only_to_its_own_check() -> None:
    """A backend exception does not turn the other checks on the same code line into expected failures."""
    text = "\n".join(
        [
            "// CHECK test_a: line_hits == 1",
            "// CHECK test_b: line_hits == 0 [xfail: llvm]",
            "return value;",
        ]
    )
    checks = parse_coverage_checks("fixture.cpp", text)
    assert checks[0].xfail_backend is None
    assert checks[1].xfail_backend == "llvm"
    assert checks[1].expected_hits == 0


@pytest.mark.parametrize("statement", ['use("http://example.test");', 'use("/* text */");', "use('/');"])
def test_comment_delimiters_in_literals_do_not_hide_code(statement: str) -> None:
    """Strings and characters remain executable source even when their contents look like comments."""
    checks = parse_coverage_checks("fixture.cpp", f"// CHECK test_a: line_hits == 1\n{statement}\nnext();")
    assert checks[0].line == 2


@pytest.mark.parametrize(
    "annotation",
    [
        "// CHECK test_a: line_hits == -1",
        "// CHECK test_a: unknown_metric == 1",
        "// CHECK test_a: line_hits = 1",
        "// CHECK test_a: line_hits == 1 test_b=2",
        "// CHECK test_a: line_hits == 1 [xfail: unknown_backend]",
        "// CHECK: line_hits == 1",
    ],
)
def test_malformed_checks_fail_with_the_annotation_location(annotation: str) -> None:
    """A typo must fail collection, rather than silently removing an assertion from validation."""
    with pytest.raises(ValueError, match=r"fixture.cpp:1: malformed coverage CHECK"):
        parse_coverage_checks("fixture.cpp", f"{annotation}\nreturn value;")


def test_duplicate_checks_for_the_same_run_and_metric_are_rejected() -> None:
    """Repeated assertions on the same counter can hide a misplaced or contradictory expectation."""
    text = "// CHECK test_a: line_hits == 1\n// CHECK test_a: line_hits == 2\nreturn value;"
    with pytest.raises(ValueError, match=r"fixture.cpp:2: duplicate CHECK"):
        parse_coverage_checks("fixture.cpp", text)


def test_check_at_end_of_file_has_no_target() -> None:
    """An orphaned expectation must fail even when comments and whitespace follow it."""
    with pytest.raises(ValueError, match=r"fixture.cpp:2: CHECK has no following code line"):
        parse_coverage_checks("fixture.cpp", "return value;\n// CHECK test_a: line_hits == 1\n// explanation\n\n")


def test_annotated_source_cannot_silently_lose_all_its_checks() -> None:
    """Files explicitly selected for annotation validation must contain at least one expectation."""
    with pytest.raises(ValueError, match="no coverage CHECKs found"):
        parse_coverage_checks("fixture.cpp", "// no checks\nreturn value;")
