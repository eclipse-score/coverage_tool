/********************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 *
 * See the NOTICE file(s) distributed with this work for additional
 * information regarding copyright ownership.
 *
 * This program and the accompanying materials are made available under the
 * terms of the Apache License Version 2.0 which is available at
 * https://www.apache.org/licenses/LICENSE-2.0
 *
 * SPDX-License-Identifier: Apache-2.0
 ********************************************************************************/

#pragma once

namespace coverage_fixture {

// Each CHECK describes one test selection and applies to the next code line,
// skipping comments and blank lines. test_a runs main with input +2; test_b
// runs it with -2; combined_tests merges the two reports without another run.
// line_hits counts executions of a line; branch_hits sums edge hits. Each individual
// test leaves an edge uncovered, and their combined report covers every edge.
// This avoids depending on backend-specific branch IDs.

// Both caller translation units include this definition. test_a calls it
// twice with +2, returning +1 each time; test_b calls it twice with -2,
// returning -1 each time. All four calls belong to this declared header.
inline int inline_sign_branch(int value) {
  // test_a: both callers pass +2, so the condition is evaluated twice.
  // CHECK test_a: branch_hits == 2

  // test_b: both callers pass -2, taking the other edge twice.
  // CHECK test_b: branch_hits == 2

  // The merged report counts all four decisions and covers both outcomes.
  // CHECK combined_tests: branch_hits == 4
  if (value > 0) {
    // test_a: both calls with +2 return here.
    // CHECK test_a: line_hits == 2

    // test_b: neither call with -2 reaches this return.
    // CHECK test_b: line_hits == 0

    // Only the two calls from test_a contribute to this return.
    // CHECK combined_tests: line_hits == 2
    return 1;
  }
  // test_a: neither call with +2 reaches this return.
  // CHECK test_a: line_hits == 0

  // test_b: both calls with -2 return here.
  // CHECK test_b: line_hits == 2

  // Only the two calls from test_b contribute to this return.
  // CHECK combined_tests: line_hits == 2
  return -1;
}

// test_a calls template<int>(+2) once from each caller and template<long>(+2L)
// once from the mixed caller. test_b makes the same calls with -2 and -2L.
// Each test therefore contributes three calls, across two type instances,
// which the report must attribute to the same source lines and branches.
template <typename T>
int template_sign_branch(T value) {
  // test_a: int(+2) is evaluated twice and long(+2L) once.
  // CHECK test_a: branch_hits == 3

  // test_b: int(-2) is evaluated twice and long(-2L) once.
  // CHECK test_b: branch_hits == 3

  // Both tests contribute three decisions; both outcomes of each instance run.
  // CHECK combined_tests: branch_hits == 6
  if (value > 0) {
    // test_a: both int(+2) calls and the long(+2L) call return here.
    // CHECK test_a: line_hits == 3

    // test_b: no call with -2 or -2L reaches this return.
    // CHECK test_b: line_hits == 0

    // Only test_a contributes these three hits across the int and long instances.
    // CHECK combined_tests: line_hits == 3
    return 1;
  }
  // test_a: no call with +2 or +2L reaches this return.
  // CHECK test_a: line_hits == 0

  // test_b: both int(-2) calls and the long(-2L) call return here.
  // CHECK test_b: line_hits == 3

  // Only test_b contributes these three hits across the int and long instances.
  // CHECK combined_tests: line_hits == 3
  return -1;
}

int exercise_int_instantiation(int value);
int exercise_int_and_long_instantiations(int value);
int call_twice_or_recover(int value);

}  // namespace coverage_fixture
