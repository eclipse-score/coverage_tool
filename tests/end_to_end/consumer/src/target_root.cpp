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
// Target-only root of the coverage scope: selected into the scope for
// //platforms:gcov_target. Never tested: 0 % via the gcno baseline on the gcov
// run, absent from the LLVM run.
namespace coverage_integration {

int target_root_value()
{
    return 2;
}

}  // namespace coverage_integration
