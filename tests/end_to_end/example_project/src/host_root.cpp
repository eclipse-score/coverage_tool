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
// Host-only root of the coverage scope: selected into the scope on the host
// platform, incompatible with //platforms:gcov_target. Never tested: 0 % via
// the baseline on the LLVM run, absent from the gcov run.
namespace coverage_integration {

int host_root_value()
{
    return 1;
}

}  // namespace coverage_integration
