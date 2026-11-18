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

#include "cpp_semantics/inline_and_templates.h"

namespace coverage_fixture {

// Each CHECK describes one selection: test_a runs main with +2; test_b runs
// main with -2. combined_tests runs both programs again and merges their
// counters into one report.
// It applies to the next code line, skipping comments and blank lines.

// call_twice_or_recover(+2) in test_a calls this twice, each time returning +2.
// call_twice_or_recover(-2) in test_b calls this once and catches the thrown -2;
// that exception prevents the second call. Throwing an int avoids dependencies
// on exception-library internals in the fixture.
int throw_if_negative(int value) {
  // test_a: the first and second calls both pass +2 and take the normal path.
  // CHECK test_a: branch_hits == 2

  // test_b: the first call passes -2 and takes the throw path.
  // CHECK test_b: branch_hits == 1

  // Two normal decisions from test_a plus one throwing decision from test_b.
  // CHECK combined_tests: branch_hits == 3
  if (value < 0) {
    // test_a: neither call with +2 throws.
    // CHECK test_a: line_hits == 0

    // test_b: the first call with -2 throws once; there is no second call.
    // CHECK test_b: line_hits == 1

    // Only test_b contributes a hit on the throw statement.
    // CHECK combined_tests: line_hits == 1
    throw value;
  }
  // test_a: both calls with +2 reach the normal return.
  // CHECK test_a: line_hits == 2

  // test_b: the call with -2 throws before reaching the return.
  // CHECK test_b: line_hits == 0

  // The merged report retains the two normal returns from test_a.
  // CHECK combined_tests: line_hits == 2
  return value;
}

// The driver calls this once per test: with +2 in test_a, returning +2, and
// with -2 in test_b, recovering from the first call's exception and returning 0.
// Separate call lines expose any execution attributed after the throwing call.
int call_twice_or_recover(int value) {
  try {
    // test_a: main calls call_twice_or_recover(+2), reaching the first call once.
    // CHECK test_a: line_hits == 1

    // test_b: main calls call_twice_or_recover(-2), also reaching this call once.
    // CHECK test_b: line_hits == 1

    // One execution from each test contributes to the first call's line.
    // CHECK combined_tests: line_hits == 2
    throw_if_negative(value);

    // test_a: the first call with +2 returns, so the second runs once with +2.
    // CHECK test_a: line_hits == 1

    // test_b: the first call with -2 throws, so this second call never runs.
    // Clang can nevertheless mark it as executed during exception unwinding:
    // https://clang.llvm.org/docs/SourceBasedCodeCoverage.html#drawbacks-and-limitations
    // Strict XFAIL makes a future upstream fix visible as XPASS.
    // CHECK test_b: line_hits == 0 [xfail: llvm]

    // Only test_a actually executes this line. LLVM inherits the same overcount
    // from test_b when merging; retain the semantic expectation as strict XFAIL.
    // CHECK combined_tests: line_hits == 1 [xfail: llvm]
    return throw_if_negative(value);
  } catch (int) {
    // test_a: both calls with +2 return normally; the catch is never entered.
    // CHECK test_a: line_hits == 0

    // test_b: the first call with -2 throws; the catch returns 0 once.
    // CHECK test_b: line_hits == 1

    // Only test_b contributes a hit in the catch handler.
    // CHECK combined_tests: line_hits == 1
    return 0;
  }
}

// Neither test calls this function (it has no arguments). External linkage
// keeps it in the instrumented object with the exercised exception code.
int uncalled_sentinel() {
  // test_a: main never calls this function.
  // CHECK test_a: line_hits == 0

  // test_b: main never calls this function either.
  // CHECK test_b: line_hits == 0

  // Merging two reports cannot make this unexecuted return covered.
  // CHECK combined_tests: line_hits == 0
  return 123;
}

}  // namespace coverage_fixture
