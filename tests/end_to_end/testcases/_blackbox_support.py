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
from html.parser import HTMLParser
from pathlib import Path

from attribute_plugin import Decorator, DerivationTechnique, add_test_properties


class HtmlPage(HTMLParser):
    """Read links, stylesheets and table cells without depending on HTML formatting or CSS classes."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self.links: list[str] = []
        self.stylesheets: list[str] = []
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.feed(content)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        href = attributes.get("href")
        if tag == "a" and href:
            self.links.append(href)
        if tag == "link" and href and "stylesheet" in (attributes.get("rel") or "").split():
            self.stylesheets.append(href)
        if tag == "tr":
            self._row = []
        if tag in ("td", "th"):
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None:
            if self._row is not None:
                self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        if tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def run_bazel(
    workspace: Path,
    args: list[str],
    *,
    expected_exit_code: int = 0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a consumer-facing Bazel command, check its exit code and capture its output.

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
    result = subprocess.run(
        [command, *args],
        cwd=workspace,
        env=process_env,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == expected_exit_code, (
        f"command: {' '.join(result.args)}\n"
        f"expected exit code {expected_exit_code}, got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def lcov_records(content: str) -> dict[str, list[str]]:
    """Index LCOV records by source path, ignoring comments and function metadata.

    The hand-derived reference validates line and branch data, independently
    of entry order and compiler-generated function names. Reject duplicate or
    incomplete records rather than hiding them during normalization.
    """
    records: dict[str, list[str]] = {}
    source: str | None = None
    entries: list[str] = []
    for line in content.splitlines():
        if not line or line.startswith(("#", "FN")):
            continue
        if line.startswith("SF:"):
            assert source is None, f"Unterminated LCOV record for {source}"
            source, entries = line[3:], []
        elif line == "end_of_record":
            assert source is not None, "LCOV record has no source path"
            assert source not in records, f"Duplicate LCOV record for {source}"
            records[source] = sorted(entries)
            source = None
        else:
            assert source is not None, f"LCOV entry outside a source record: {line}"
            entries.append(line)
    assert source is None, f"Unterminated LCOV record for {source}"
    return records


def verifies(*requirements: str, derivation: DerivationTechnique = "requirements-analysis") -> Decorator:
    """Attach requirement metadata to a plain pytest interface scenario."""
    # Keep this adapter temporary until the project settles how score_pytest
    # and sphinx-needs-test-reports should provide metadata for pytest functions.
    return add_test_properties(
        partially_verifies=list(requirements),
        test_type="interface-test",
        derivation_technique=derivation,
    )
