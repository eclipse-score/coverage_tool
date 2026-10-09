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
"""Local Bazel execution and requirement metadata for end-to-end pytest cases."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from attribute_plugin import Decorator, DerivationTechnique, add_test_properties


def run_bazel(
    workspace: Path,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a consumer-facing Bazel command and capture its user-visible output.

    ``env`` overrides selected inherited variables for a single invocation,
    while preserving the rest of the host environment.
    """
    command = shutil.which("bazel")
    assert command, "Bazel must be available on PATH to run the integration scenarios"
    process_env = os.environ.copy()
    # A nested coverage command must not append its output to the enclosing CI
    # step's summary; only the outer workflow owns that summary file.
    process_env.pop("GITHUB_STEP_SUMMARY", None)
    if env:
        process_env.update(env)
    # Bazel uses TEST_TMPDIR as the nested command's default output root. Remove
    # the outer test's disposable value so nested Bazel can reuse the consumer's
    # normal output base, extracted toolchains and the host download cache.
    process_env.pop("TEST_TMPDIR", None)
    return subprocess.run(
        [command, *args],
        cwd=workspace,
        env=process_env,
        capture_output=True,
        check=False,
        text=True,
    )


def assert_exit_code(result: subprocess.CompletedProcess[str], expected: int) -> None:
    assert result.returncode == expected, (
        f"command: {' '.join(result.args)}\n"
        f"expected exit code {expected}, got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def verifies(*requirements: str, derivation: DerivationTechnique = "requirements-analysis") -> Decorator:
    """Attach requirement metadata to a plain pytest interface scenario."""
    # Keep this adapter temporary until the project settles how score_pytest
    # and sphinx-needs-test-reports should provide metadata for pytest functions.
    return add_test_properties(
        partially_verifies=list(requirements),
        test_type="interface-test",
        derivation_technique=derivation,
    )
