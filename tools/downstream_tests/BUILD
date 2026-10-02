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

# Each test runs the consumer's full coverage pipeline, which can take many
# minutes on a cold CI runner. The tests need network access to clone current
# consumer main branches and run Bazel in those nested workspaces.
#
# Keep each consumer scenario in its own target so CI and JUnit reports show
# exactly which real downstream workflow failed.
score_pytest(
    name = "baselibs",
    size = "large",
    timeout = "eternal",
    srcs = ["test_baselibs.py"],
    data = ["_consumer_workspace.py"],
    imports = ["."],
    tags = [
        "integration",
        "local",
    ],
)

score_pytest(
    name = "lifecycle",
    size = "large",
    timeout = "eternal",
    srcs = ["test_lifecycle.py"],
    data = ["_consumer_workspace.py"],
    imports = ["."],
    tags = [
        "integration",
        "local",
    ],
)
