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
#ifndef ITEST_EXTERNAL_VEXT_H
#define ITEST_EXTERNAL_VEXT_H

namespace vext {

inline int thrice(int value) {
  return value * 3;
}

inline int never_used(int value) {
  return value + 1;
}

}  // namespace vext

#endif  // ITEST_EXTERNAL_VEXT_H
