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
"""A workspace rule that forwards the CcInfo of another target (fixture).

Consumers wrap third-party libraries this way, e.g. to apply a transition
(eclipse-score/baselibs ``third_party/openssl``). The forwarded library's
headers are then the workspace target's ``direct_public_headers`` although
the workspace target declares nothing itself (eclipse-score/coverage_tool#5).
"""

def _forward_cc_impl(ctx):
    dep = ctx.attr.dep
    return [dep[DefaultInfo], dep[CcInfo]]

forward_cc = rule(
    implementation = _forward_cc_impl,
    attrs = {
        "dep": attr.label(providers = [CcInfo], mandatory = True),
    },
)
