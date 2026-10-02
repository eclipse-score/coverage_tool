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
"""Shared helpers for black-box coverage scenarios."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from attribute_plugin import Decorator, DerivationTechnique, add_test_properties

_COVERAGE_REPORT = Path("bazel-out/_coverage/_coverage_report.dat")
JUSTIFICATIONS = "tools/coverage/coverage_justifications.yaml"
EXPECTED_UNMAPPED_LLVM = (
    "compiled-without-code\tsrc/empty_unit.cpp\n"
    "declaration-only\tlib/cross_pkg.h\n"
    "declaration-only\tsrc/coverable.h\n"
    "declaration-only\tsrc/uncovered.h\n"
    "no-data\tsrc/unused_api.h\n"
)
EXPECTED_UNMAPPED_GCOV = EXPECTED_UNMAPPED_LLVM + "not-instrumented\trust/lib.rs\nnot-instrumented\trust/main.rs\n"


@dataclass(frozen=True)
class CoverageReport:
    """A consumer workspace and a saved report produced by one backend setup."""

    workspace: Path
    backend: str
    archive: Path
    collection_output: str

    def install(self) -> Path:
        """Put this scenario's collected report at the documented Bazel path."""
        target = self.workspace / _COVERAGE_REPORT
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.chmod(target.stat().st_mode | 0o200)
        shutil.copyfile(self.archive, target)
        target.chmod(target.stat().st_mode | 0o200)
        return target


def run_bazel(
    workspace: Path,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a consumer-facing Bazel command and capture its user-visible output."""
    command = shutil.which("bazel")
    assert command, "Bazel must be available on PATH to run the integration scenarios"
    process_env = os.environ.copy()
    process_env.pop("GITHUB_STEP_SUMMARY", None)
    if env:
        process_env.update(env)
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
    """Attach score_pytest requirement metadata to an interface scenario."""
    return add_test_properties(
        partially_verifies=list(requirements),
        test_type="interface-test",
        derivation_technique=derivation,
    )


def fault_injection(*requirements: str, derivation: DerivationTechnique = "error-guessing") -> Decorator:
    """Attach score_pytest requirement metadata to a fault-injection scenario."""
    return add_test_properties(
        partially_verifies=list(requirements),
        test_type="fault-injection",
        derivation_technique=derivation,
    )


def collect_report(
    workspace: Path,
    backend: str,
    targets: list[str],
    destination: Path,
    extra_args: list[str] | None = None,
) -> CoverageReport:
    """Collect one backend report for a consumer-workspace scenario."""
    command = ["coverage", f"--config={backend}"]
    if extra_args:
        command.extend(extra_args)
    command.extend(targets)
    command.append("--build_tests_only")
    result = run_bazel(workspace, command)
    assert_exit_code(result, 0)
    collected = workspace / _COVERAGE_REPORT
    assert collected.is_file(), f"Bazel did not produce the expected {backend} coverage archive"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(collected, destination)
    return CoverageReport(workspace, backend, destination, result.stdout + result.stderr)


def generate_report(
    report: CoverageReport,
    *args: str,
    threshold: str = "10",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the public HTML-generation command against a saved backend report."""
    report.install()
    command = ["run", "@score_coverage//:generate_coverage_html", "--", *args]
    process_env = {"COVERAGE_THRESHOLD": threshold}
    if env:
        process_env.update(env)
    return run_bazel(report.workspace, command, env=process_env)


def lcov_records(text: str) -> dict[str, list[str]]:
    """Split LCOV data into source records, dropping function metadata."""
    records: dict[str, list[str]] = {}
    current: list[str] = []
    source = ""
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        if line.startswith("SF:"):
            source = line[3:]
        if line.startswith("FN"):
            continue
        current.append(line)
        if line == "end_of_record":
            records[source] = current
            current = []
            source = ""
    return records


def normalise_lcov(text: str) -> str:
    """Ignore function metadata and record order when comparing the goldens."""
    records = lcov_records(text)
    return "".join("\n".join(records[source]) + "\n" for source in sorted(records))


def lcov_from_artifacts(path: Path) -> str:
    """Read LCOV data from either a generated archive directory or ZIP file."""
    if path.is_dir():
        return (path / "coverage_report.dat").read_text(encoding="utf-8")
    with zipfile.ZipFile(path) as archive:
        member = next(
            name
            for name in archive.namelist()
            if name.endswith("lcov_report/lcov.dat") or name.endswith("coverage_report.dat")
        )
        return archive.read(member).decode("utf-8")


class LineCounts(NamedTuple):
    """Covered and found line totals from one LCOV source record."""

    hits: int
    found: int


def line_counts(records: dict[str, list[str]], source: str) -> LineCounts:
    """Return a source record's covered-line and total-line counts."""
    record = records[source]
    lines_found = next(int(line[3:]) for line in record if line.startswith("LF:"))
    lines_hit = next(int(line[3:]) for line in record if line.startswith("LH:"))
    return LineCounts(hits=lines_hit, found=lines_found)


def summary_metric(summary: str, name: str) -> float:
    """Read a named percentage from the human-readable justification summary."""
    match = re.search(rf"{re.escape(name)}:\s+([0-9.]+)%", summary)
    assert match, f"{name} missing from report summary:\n{summary}"
    return float(match.group(1))


def index_links(index: Path) -> list[str]:
    """Return coverage-page links in an HTML index page."""
    return re.findall(r"href=['\"](coverage/[^'\"]+\.html)['\"]", index.read_text(encoding="utf-8"))
