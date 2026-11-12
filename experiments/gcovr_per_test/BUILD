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

load("@pip_score_coverage//:requirements.bzl", "requirement")
load("@rules_python//python:defs.bzl", "py_binary")

# These opt-in tools investigate the per-test hook without changing the
# production collectors or the combined coverage report. The collector returns
# Bazel's usual LCOV and publishes its additional evidence as test artifacts.
py_binary(
    name = "collector",
    srcs = ["collector.py"],
    data = ["@bazel_tools//tools/test:lcov_merger"],
    tags = ["manual"],
    visibility = ["//visibility:public"],
    deps = [
        "@rules_python//python/runfiles",
        requirement("gcovr"),
    ],
)

# Use the exact gcovr version already locked by coverage_tool for both
# collection and replay; no separate Python installation is required.
py_binary(
    name = "gcovr",
    srcs = ["gcovr_cli.py"],
    main = "gcovr_cli.py",
    tags = ["manual"],
    deps = [requirement("gcovr")],
)
