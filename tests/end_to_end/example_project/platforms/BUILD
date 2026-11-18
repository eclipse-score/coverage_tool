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
# A target platform that differs from the host platform by one fixture-only
# constraint. coverage:gcov builds and runs the tests for it, while Bazel
# analyses the coverage report generator, and with it the coverage scope, in
# the exec configuration (host platform). score_coverage_scope(platform = ...)
# makes the scope follow this platform (coverage_tool#23).
package(default_visibility = ["//visibility:public"])

constraint_setting(name = "fixture_flavour")

constraint_value(
    name = "gcov_target_marker",
    constraint_setting = ":fixture_flavour",
)

platform(
    name = "gcov_target",
    constraint_values = [":gcov_target_marker"],
    parents = ["@score_bazel_platforms//:x86_64-linux-gcc_12.2.0-posix"],
)

config_setting(
    name = "is_gcov_target",
    constraint_values = [":gcov_target_marker"],
)
