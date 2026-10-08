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
#ifndef COVERAGE_INTEGRATION_TESTS_SRC_UNUSED_API_H
#define COVERAGE_INTEGRATION_TESTS_SRC_UNUSED_API_H

// Public API nobody in this workspace includes, and template-only on top:
// no translation unit produces code from it, so llvm-cov has no coverage
// mapping for the file. The pipeline must still name it as an in-scope file
// without coverage data instead of silently leaving it out.
namespace coverage_integration {

template <typename T>
struct UnusedApi {
  T value;
  bool IsPositive() const { return value > T{}; }
};

}  // namespace coverage_integration

#endif  // COVERAGE_INTEGRATION_TESTS_SRC_UNUSED_API_H
