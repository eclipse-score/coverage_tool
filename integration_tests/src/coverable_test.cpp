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
#include <cstring>

#include "extlib/extlib.h"
#include "src/coverable.h"
#include "vendored/inline_math.h"
#include "vext/vext.h"

// Deliberately exercises only the negative and zero branches; the positive
// branch stays uncovered (and justified via the COV_JUSTIFIED marker).
int main() {
  using coverage_integration::classify;
  if (std::strcmp(classify(-5), "negative") != 0) {
    return 1;
  }
  if (std::strcmp(classify(0), "zero") != 0) {
    return 1;
  }
  if (coverage_integration::twice(21) != 42) {
    return 1;
  }
  // Third-party code reached through a forwarding workspace target: executed,
  // instrumented, and expected to stay out of the report.
  if (extlib::add(1, 2) != 3) {
    return 1;
  }
  // Header vendored from the external module: in scope, called once.
  if (vext::thrice(2) != 6) {
    return 1;
  }
  return 0;
}
