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

// test_a: the driver calls this once with value=+2; it returns +3.
// test_b: the driver calls this once with value=-2; it returns -3.
// Each invocation forwards value to the inline function and template<int>,
// and converts it to +2L or -2L for template<long>.
//
// Keep this caller in a separate translation unit: it duplicates the inline
// function and int instance from int_template_caller.cpp, and adds a long
// instance. This distinguishes merging shared definitions across translation
// units from combining different template instances at the same source lines.
int exercise_int_and_long_instantiations(int value) {
  return inline_sign_branch(value) + template_sign_branch<int>(value) +
         template_sign_branch<long>(value);
}

}  // namespace coverage_fixture
