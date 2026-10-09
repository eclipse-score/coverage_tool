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
"""The checked-in consumer workspace for local end-to-end pytest cases."""

import shutil
from pathlib import Path

import pytest

# This local-only target needs symlinked runfiles: resolve() follows conftest.py
# back into the checkout. Copied runfiles and remote execution cannot supply
# the consumer workspace or the host Bazel installation used by the fixtures.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CONSUMER_WORKSPACE_DIRECTORY = "tests/end_to_end/consumer"


@pytest.fixture(scope="session")
def consumer_workspace() -> Path:
    """Reuse the consumer's Bazel outputs, including its extracted toolchains."""
    if not (_REPOSITORY_ROOT / "MODULE.bazel").is_file():
        pytest.fail(
            "Black-box tests require local execution with symlinked runfiles pointing "
            f"into the source checkout; MODULE.bazel is missing at {_REPOSITORY_ROOT}",
            pytrace=False,
        )
    if shutil.which("bazel") is None:
        pytest.fail("Black-box tests require the host Bazel installation on PATH", pytrace=False)
    return _REPOSITORY_ROOT / _CONSUMER_WORKSPACE_DIRECTORY
