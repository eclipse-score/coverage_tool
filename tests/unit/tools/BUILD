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

load("@rules_python//python:defs.bzl", "py_test")

# Run the gate's existing unittest suite with the importable implementation
# supplied by //tools, where the executable used by CI also lives.
py_test(
    name = "self_coverage_gate_test",
    srcs = ["self_coverage_gate_test.py"],
    main = "self_coverage_gate_test.py",
    deps = ["//tools:self_coverage_gate_lib"],
)
