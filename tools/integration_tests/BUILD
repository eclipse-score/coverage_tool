# *******************************************************************************
# Copyright (c) 2026 Contributors to the Eclipse Foundation
#
# See the NOTICE file(s) distributed with this work for additional
# information regarding copyright ownership.
#
# This program and the accompanying materials are made available under the
# terms of the Apache License Version 2.0 which is available at
# https://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0
# *******************************************************************************

load("@score_tools//score_pytest:pytest.bzl", "score_pytest")

score_pytest(
    name = "blackbox_test",
    srcs = [
        "test_error_handling.py",
        "test_gcov.py",
        "test_llvm_gates.py",
        "test_llvm_reports.py",
    ],
    # score_pytest passes srcs to pytest as collection paths. Keep shared
    # fixtures and helpers in runfiles without presenting them as test modules.
    data = [
        "_blackbox_support.py",
        "conftest.py",
    ],
    imports = ["."],
    size = "large",
    tags = ["integration", "local"],
    timeout = "long",
)
