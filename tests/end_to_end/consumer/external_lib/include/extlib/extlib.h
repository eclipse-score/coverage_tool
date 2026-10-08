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
#ifndef ITEST_EXTERNAL_EXTLIB_H
#define ITEST_EXTERNAL_EXTLIB_H

namespace extlib {

// Third-party code: instrumented like everything else under
// --experimental_use_llvm_covmap, but not part of the workspace's scope.
int add(int a, int b);

}  // namespace extlib

#endif  // ITEST_EXTERNAL_EXTLIB_H
