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

#include <cstdlib>

#include "cpp_semantics/inline_and_templates.h"

// test_a invokes main with argc=2 and argv[1]="2"; the driver passes
// value=+2 once to each exercise function and to call_twice_or_recover.
// test_b invokes main with argc=2 and argv[1]="-2"; the same calls use
// value=-2, causing call_twice_or_recover to exercise its catch handler.
// The E2E suite measures each test separately and then their combined report.
// This driver is instrumented but outside the library's declared scope, so
// its own source must be excluded from the final coverage report.
int main(int argc, char** argv) {
  if (argc != 2) {
    return 2;
  }
  const int value = std::atoi(argv[1]);
  if (value != 2 && value != -2) {
    return 2;
  }

  // Evaluate every scenario before checking results so all intended calls
  // execute even if one result is wrong. The sums also make each shared
  // inline/template invocation observable to the test driver.
  const int int_instance_result =
      coverage_fixture::exercise_int_instantiation(value);
  const int mixed_instances_result =
      coverage_fixture::exercise_int_and_long_instantiations(value);
  const int exception_result = coverage_fixture::call_twice_or_recover(value);

  const int expected_sign = value > 0 ? 1 : -1;
  const int expected_exception_result = value < 0 ? 0 : value;
  if (int_instance_result != 2 * expected_sign ||
      mixed_instances_result != 3 * expected_sign ||
      exception_result != expected_exception_result) {
    return 1;
  }
  return 0;
}
