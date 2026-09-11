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
#ifndef COVERAGE_INTEGRATION_TESTS_SRC_VENDORED_INLINE_MATH_H
#define COVERAGE_INTEGRATION_TESTS_SRC_VENDORED_INLINE_MATH_H

namespace coverage_integration {

inline int twice(int value) {
  return value * 2;
}

inline int never_inlined(int value) {
  return value - 1;
}

}  // namespace coverage_integration

#endif  // COVERAGE_INTEGRATION_TESTS_SRC_VENDORED_INLINE_MATH_H
