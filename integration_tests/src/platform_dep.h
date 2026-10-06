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
#ifndef COVERAGE_INTEGRATION_TESTS_SRC_PLATFORM_DEP_H
#define COVERAGE_INTEGRATION_TESTS_SRC_PLATFORM_DEP_H

namespace coverage_integration {

// Implemented once per platform variant (platform_host.cpp /
// platform_target.cpp); the scope must list the variant of the platform the
// coverage run targets.
int platform_value();

}  // namespace coverage_integration

#endif  // COVERAGE_INTEGRATION_TESTS_SRC_PLATFORM_DEP_H
