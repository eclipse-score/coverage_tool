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
    size = "large",
    timeout = "long",
    srcs = [
        "test_cli.py",
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
    # These scenarios read a consumer workspace from the checkout and invoke
    # the host Bazel installation. Those inputs are outside this target's
    # runfiles, so their changes cannot invalidate Bazel's test-result cache.
    # The external tag makes Bazel execute the tests on every invocation;
    # local keeps the nested Bazel processes on the machine with the checkout.
    tags = [
        "external",
        "integration",
        "local",
    ],
)
