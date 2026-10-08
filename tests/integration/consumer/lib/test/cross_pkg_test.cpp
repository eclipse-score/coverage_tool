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
 *******************************************************************************/
#include "lib/cross_pkg.h"

// Calls pick() with a small value only: the `return 1` line and the true
// direction of the condition stay uncovered.
int main()
{
    return crosspkg::pick(3) == 0 ? 0 : 1;
}
