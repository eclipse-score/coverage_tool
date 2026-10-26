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
"""Regression checks for downstream command output and failure diagnostics."""

import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _consumer_workspace import run_bazel


class ConsumerWorkspaceTest(unittest.TestCase):
    """Use a real subprocess so decoding behavior is exercised as well."""

    def run_command(self, root: Path, source: str) -> None:
        """Replace only Bazel itself; keep subprocess capture and artifact writes real."""
        workspace = root / "logging"
        workspace.mkdir()
        launcher = root / "bazel"
        # Bazel's interpreter path can exceed the kernel's shebang length limit.
        launcher.write_text(
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -c {shlex.quote(source)} "$@"\n', encoding="utf-8"
        )
        launcher.chmod(0o755)
        with patch.dict(
            os.environ,
            {
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
                "TEST_UNDECLARED_OUTPUTS_DIR": str(root / "outputs"),
            },
        ):
            run_bazel(workspace, "coverage", "--config=llvm_cov")

    def test_successful_build_with_non_utf8_output_retains_readable_log(self) -> None:
        """A consumer's arbitrary output bytes must not turn a successful build red."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.run_command(root, 'import os\nos.write(1, b"build succeeded\\n")\nos.write(2, b"message: \\xff\\n")\n')

            log = (root / "outputs/logging/coverage.log").read_text(encoding="utf-8")
            self.assertEqual(log, "build succeeded\nmessage: \ufffd\n")
            summary = (root / "outputs/logging/compatibility_summary.md").read_text(encoding="utf-8")
            self.assertIn("logging: bazel coverage — PASSED", summary)
            self.assertIn("Exit code: 0", summary)

    def test_failure_preserves_early_error_and_full_log(self) -> None:
        """A long skipped-test list must not hide the actual repository error."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with self.assertRaises(AssertionError) as failure:
                self.run_command(
                    root,
                    'import sys\nprint("ERROR: dependency checksum mismatch")\n'
                    'print("skipped test\\n" * 100, end="")\nsys.exit(7)\n',
                )

            message = str(failure.exception)
            self.assertIn("logging: bazel coverage — FAILED", message)
            self.assertIn("bazel coverage --config=llvm_cov", message)
            self.assertIn("Exit code: 7", message)
            self.assertIn("ERROR: dependency checksum mismatch", message)
            self.assertIn("coverage.log", message)
            log = (root / "outputs/logging/coverage.log").read_text(encoding="utf-8")
            self.assertEqual(log.count("skipped test"), 100)
            summary = (root / "outputs/logging/compatibility_summary.md").read_text(encoding="utf-8")
            self.assertIn(message, summary)


if __name__ == "__main__":
    unittest.main()
