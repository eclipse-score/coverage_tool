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
"""Prepare real consumer workspaces for the downstream coverage scenarios."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

_COVERAGE_TOOL_ROOT = Path(__file__).resolve().parents[2]


def clone_consumer(name: str, parent_directory: Path) -> Path:
    """Clone a consumer's default branch and point it at this checkout."""
    workspace = parent_directory / name
    repository_url = f"https://github.com/eclipse-score/{name}.git"
    subprocess.run(
        ["git", "clone", "--depth", "1", repository_url, str(workspace)],
        check=True,
    )

    tool_link = parent_directory / "coverage_tool"
    tool_link.symlink_to(_COVERAGE_TOOL_ROOT, target_is_directory=True)

    module_file = workspace / "MODULE.bazel"
    module_contents = module_file.read_text(encoding="utf-8")
    module_contents = (
        module_contents.rstrip()
        + '\n\nlocal_path_override(\n    module_name = "score_coverage",\n    path = "../coverage_tool",\n)\n'
    )
    module_file.write_text(module_contents, encoding="utf-8")

    return workspace


def run_bazel(
    workspace: Path,
    *arguments: str,
    extra_environment: dict[str, str] | None = None,
) -> None:
    """Run Bazel and retain a readable status summary plus its complete output."""
    environment = os.environ.copy()
    if extra_environment:
        environment.update(extra_environment)

    command = ["bazel", *arguments]
    result = subprocess.run(
        command,
        cwd=workspace,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    status = "FAILED" if result.returncode else "PASSED"
    summary = (
        f"### {workspace.name}: bazel {arguments[0]} — {status}\n\n"
        f"Command: `{shlex.join(command)}`\n\n"
        f"Exit code: {result.returncode}\n"
    )
    if result.returncode:
        lines = result.stdout.splitlines()
        # Compiler and repository errors can precede a long list of skipped
        # tests. Show those diagnostics before the tail rather than losing them.
        diagnostics = [line for line in lines if any(marker in line for marker in ("ERROR:", "FAIL:", "Error in "))]
        excerpt = "\n".join(diagnostics[:10] + lines[-30:])
        summary += f"\n```text\n{excerpt}\n```\n"

    outputs_directory = os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR")
    if outputs_directory:
        retained = Path(outputs_directory) / workspace.name
        retained.mkdir(parents=True, exist_ok=True)
        log_name = f"{arguments[0]}.log"
        (retained / log_name).write_text(result.stdout, encoding="utf-8")
        summary += f"\nFull output: `{log_name}` in the uploaded test artifacts.\n"
        with (retained / "compatibility_summary.md").open("a", encoding="utf-8") as summary_file:
            summary_file.write(summary + "\n")
    if result.returncode:
        raise AssertionError(summary)


def retain_coverage_results(workspace: Path, archive_directory: str) -> None:
    """Keep whatever report files exist, including reports from a failed gate."""
    archive = workspace / archive_directory
    html_report = archive / "coverage_linux"
    lcov_report = archive / "coverage_report.dat"
    outputs_directory = os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR")
    if not archive.is_dir() or not outputs_directory:
        return

    retained_report = Path(outputs_directory) / workspace.name / "coverage-report"
    summary_markdown = workspace / "coverage_summary.md"
    try:
        retained_report.mkdir(parents=True, exist_ok=True)
        if html_report.is_dir():
            shutil.copytree(html_report, retained_report / "coverage_linux")
        if lcov_report.is_file():
            shutil.copy2(lcov_report, retained_report / lcov_report.name)
        if summary_markdown.is_file():
            shutil.copy2(summary_markdown, retained_report / summary_markdown.name)

        for name in ("justification_report", "unmapped_files.txt"):
            result = archive / name
            if result.is_dir():
                shutil.copytree(result, retained_report / name)
            elif result.is_file():
                shutil.copy2(result, retained_report / name)
    except Exception as error:  # pylint: disable=broad-exception-caught
        print(f"Could not copy all coverage report files: {error}", file=sys.stderr)

    try:
        report_archive = Path(shutil.make_archive(str(retained_report), "zip", retained_report))
    except Exception as error:  # pylint: disable=broad-exception-caught
        print(f"Could not archive the coverage report: {error}", file=sys.stderr)
        return

    try:
        shutil.rmtree(retained_report)
    except OSError as error:
        print(f"Could not remove the unpacked coverage report: {error}", file=sys.stderr)

    print(f"Coverage report retained at {report_archive}.")


def verify_coverage_results(workspace: Path, archive_directory: str) -> None:
    """Require measurable coverage after retaining all available report files."""
    archive = workspace / archive_directory
    html_report = archive / "coverage_linux"
    lcov_report = archive / "coverage_report.dat"
    summary_markdown = workspace / "coverage_summary.md"

    assert (html_report / "index.html").is_file(), "Coverage HTML index was not generated"
    assert lcov_report.is_file(), "LCOV coverage report was not generated"
    assert summary_markdown.is_file(), "Markdown coverage summary was not generated"

    source_files = 0
    lines_found = 0
    lines_hit = 0
    for line in lcov_report.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("SF:"):
            source_files += 1
        elif line.startswith("LF:"):
            lines_found += int(line[3:])
        elif line.startswith("LH:"):
            lines_hit += int(line[3:])

    assert source_files > 0, "LCOV report contains no source files"
    assert lines_found > 0, "LCOV report contains no measurable lines"
    assert lines_hit > 0, "LCOV report contains no covered lines"

    outputs_directory = os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR")
    assert outputs_directory, "Bazel did not provide TEST_UNDECLARED_OUTPUTS_DIR"
    report_archive = Path(outputs_directory) / workspace.name / "coverage-report.zip"
    assert report_archive.is_file(), "Coverage report was not retained for Bazel"

    coverage_percent = 100 * lines_hit / lines_found
    print(
        f"Coverage report contains {source_files} source files and "
        f"{lines_hit}/{lines_found} covered lines ({coverage_percent:.2f}%). "
        f"Report retained at {report_archive}."
    )
