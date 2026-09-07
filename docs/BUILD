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

load("@score_docs_as_code//:docs.bzl", "docs")

# Documentation (docs-as-code). Lives in its own package on purpose: the root
# package must not load from dev dependencies (consumers do not have them).
# Targets: //docs:docs, //docs:incremental, //docs:live_preview, //docs:ide_support.
docs(
    external_needs = ["@score_process_description//:needs_json"],
    project = "score_coverage",
    project_url = "https://eclipse-score.github.io/coverage_tool",
    source_dir = ".",
)
