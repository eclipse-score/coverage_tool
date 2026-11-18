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
// Entry point of a shipped binary. Nothing tests it; the report must still
// list it at 0 % (coverage_tool#40). Linked straight into the executable, so
// its mapping lives in no archive: the executable is its baseline object.
int main()
{
    return 0;
}
