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
    srcs = ["test_cli.py"],
    # score_pytest passes srcs to pytest as collection paths. Keep shared
    # fixtures and helpers in runfiles without presenting them as test modules.
    data = [
        "_blackbox_support.py",
        "conftest.py",
    ],
    imports = ["."],
    # The checkout and host Bazel installation are runtime inputs outside this
    # target's runfiles, so changes to them cannot invalidate a cached result.
    # `external` disables test caching; `integration` lets callers select these
    # scenarios with --test_tag_filters; `local` keeps the host Bazel process
    # with the checkout instead of using sandboxed or remote execution.
    tags = [
        "external",
        "integration",
        "local",
    ],
)
