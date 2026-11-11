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

load("@rules_python//python:defs.bzl", "py_library")
load("@score_tools//score_pytest:pytest.bzl", "score_pytest")

# Unit tests run the command helper with a fake Bazel executable to cover
# malformed output and failure reporting without downloading consumer toolchains.
py_library(
    name = "consumer_workspace",
    srcs = ["_consumer_workspace.py"],
    imports = ["."],
    visibility = ["//tests/unit/tools:__pkg__"],
)

# Each test runs the consumer's full coverage pipeline, which can take many
# minutes on a cold CI runner. The tests need network access to clone current
# consumer main branches and run Bazel in those nested workspaces.
#
# The parametrized test runs all consumers by default. CI selects one with -k
# so each job reports its own result; report archives use consumer subdirectories.
score_pytest(
    name = "consumers",
    size = "large",
    timeout = "eternal",
    srcs = ["test_consumers.py"],
    args = ["--tb=short"],
    tags = [
        "integration",
        "local",
    ],
    deps = [":consumer_workspace"],
)
