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

// test_a: the driver calls this once with value=+2; it returns +2.
// test_b: the driver calls this once with value=-2; it returns -2.
// Each invocation forwards value unchanged to the inline function and the int
// template instance. The driver checks their sum to make both calls observable.
int exercise_int_instantiation(int value) {
  return inline_sign_branch(value) + template_sign_branch<int>(value);
}

}  // namespace coverage_fixture
