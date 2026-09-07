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
"""Generate the HTML coverage report from `bazel coverage` output and gate it.

The LLVM pipeline's reporter leaves a zip at bazel-out/_coverage/_coverage_report.dat
containing html_report/, lcov_report/ and text_report/. This tool

1. extracts the HTML report into the output directory,
2. optionally applies coverage justifications (--yaml) and computes the
   effective-coverage metric,
3. writes an optional markdown summary (--summary-md or GITHUB_STEP_SUMMARY),
4. optionally assembles an artifacts tree / zip (--archive-dir / --archive),
5. enforces COVERAGE_THRESHOLD on the gated metric: effective line coverage
   when --yaml is given, raw line coverage from the LCOV data otherwise.

Usage (from the CONSUMER workspace, after `bazel coverage --config=llvm_cov`):

    bazel run @score_coverage//:generate_coverage_html -- \\
        [--yaml <path/to/coverage_justifications.yaml>] \\
        [--archive <archive-name>] [--archive-dir <dir>] \\
        [--platform <platform>] [--testlogs-subdir <subdir>] \\
        [--summary-md <path>] [output-dir]

Exit codes:
    0  gate passed
    1  gate failed (gated coverage below COVERAGE_THRESHOLD)
    2  the run could not be evaluated (missing/invalid inputs, bad threshold,
       justification errors). This is deliberately distinct from 0: a report
       that cannot be produced must never look like a passing gate.

Design note: the threshold gate is the one decision downstream safety
arguments rely on, which is why it lives in small pure functions here
(``parse_threshold``, ``raw_line_coverage_from_lcov``,
``effective_line_coverage_from_report``, ``gate_passes``) that are unit tested
independently of Bazel. The comparison uses the UNROUNDED percentage: a
value printed as "100.00" but actually 99.995 must not pass a threshold of
100.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from score_coverage import coverage_summary, effective_coverage, justify

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_ERROR = 2

DEFAULT_THRESHOLD = 100.0
COVERAGE_REPORT_REL = Path("bazel-out/_coverage/_coverage_report.dat")


class GenerateError(Exception):
    """A condition under which no verdict can be produced (exit code 2)."""


@dataclass
class Options:
    """Parsed command line."""

    yaml: str | None
    archive: str | None
    archive_dir: str | None
    platform: str
    testlogs_subdir: str
    summary_md: str | None
    output_dir: str | None


def parse_args(argv: Sequence[str] | None = None) -> Options:
    """Parse the command line (``argv`` defaults to ``sys.argv[1:]``)."""
    parser = argparse.ArgumentParser(
        prog="generate_coverage_html",
        description="Extract the LLVM coverage HTML report, apply justifications and gate on the threshold.",
    )
    parser.add_argument("--yaml", metavar="PATH", help="Justification YAML, relative to the workspace root.")
    parser.add_argument("--archive", metavar="NAME", help="Write an artifacts zip named NAME.zip.")
    parser.add_argument("--archive-dir", metavar="DIR", help="Assemble the artifacts tree into DIR (not zipped).")
    parser.add_argument(
        "--platform",
        default="linux",
        choices=sorted(justify.VALID_PLATFORMS),
        help="Target platform for justification filtering (default: linux).",
    )
    parser.add_argument(
        "--testlogs-subdir",
        default="",
        metavar="SUBDIR",
        help="Subdirectory of bazel-testlogs to collect JUnit XMLs from when archiving.",
    )
    parser.add_argument("--summary-md", metavar="PATH", help="Write the markdown coverage summary to PATH.")
    parser.add_argument(
        "output_dir",
        nargs="?",
        help="Directory for the HTML report (default: coverage_<platform>).",
    )
    ns = parser.parse_args(argv)
    return Options(
        yaml=ns.yaml,
        archive=ns.archive,
        archive_dir=ns.archive_dir,
        platform=ns.platform,
        testlogs_subdir=ns.testlogs_subdir,
        summary_md=ns.summary_md,
        output_dir=ns.output_dir,
    )


# -----------------------------------------------------------------------------
# Gate primitives (pure, unit tested)
# -----------------------------------------------------------------------------


def parse_threshold(value: str | None) -> float:
    """Return the coverage threshold in percent.

    ``None`` or an empty string means the default (100). Anything that is not
    a number in [0, 100] is an error: a misspelt threshold must never turn
    into a permissive gate.
    """
    if value is None or value.strip() == "":
        return DEFAULT_THRESHOLD
    try:
        threshold = float(value)
    except ValueError as exc:
        raise GenerateError(f"COVERAGE_THRESHOLD must be a number, got {value!r}") from exc
    if math.isnan(threshold) or not 0.0 <= threshold <= 100.0:
        raise GenerateError(f"COVERAGE_THRESHOLD must be within [0, 100], got {value!r}")
    return threshold


def raw_line_coverage_from_lcov(lcov_path: Path) -> float:
    """Sum LF/LH over all records of an LCOV file and return the percentage.

    The LCOV file (not llvm-cov's text summary) is used on purpose: it
    includes the baseline-only records of in-scope files no test links
    against, which the text summary omits. A file with no instrumented
    lines at all (LF total 0) yields no verdict and is an error.
    """
    if not lcov_path.is_file():
        raise GenerateError(f"lcov_report/lcov.dat not found at {lcov_path}")
    lines_found = 0
    lines_hit = 0
    with open(lcov_path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("LF:"):
                lines_found += _lcov_int(line)
            elif line.startswith("LH:"):
                lines_hit += _lcov_int(line)
    if lines_found <= 0:
        raise GenerateError(f"could not compute raw line coverage from {lcov_path}: no instrumented lines")
    if lines_hit > lines_found:
        raise GenerateError(f"corrupt LCOV data in {lcov_path}: LH total {lines_hit} exceeds LF total {lines_found}")
    return 100.0 * lines_hit / lines_found


def _lcov_int(record: str) -> int:
    key, _, value = record.partition(":")
    try:
        number = int(value)
    except ValueError as exc:
        raise GenerateError(f"malformed LCOV record {record!r}") from exc
    if number < 0:
        raise GenerateError(f"malformed LCOV record {record!r}: negative {key}")
    return number


def effective_line_coverage_from_report(report_path: Path) -> float:
    """Read the effective line coverage percentage from effective_coverage's report.json."""
    if not report_path.is_file():
        raise GenerateError(f"effective coverage report was not produced: {report_path}")
    try:
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        value = report["summary"]["effective_line_coverage_pct"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise GenerateError(
            f"effective coverage report {report_path} is missing summary.effective_line_coverage_pct"
        ) from exc
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise GenerateError(f"effective_line_coverage_pct in {report_path} is not a number: {value!r}")
    return float(value)


def gate_passes(coverage_pct: float, threshold_pct: float) -> bool:
    """The gate passes when the (unrounded) coverage reaches the threshold."""
    return coverage_pct >= threshold_pct


# -----------------------------------------------------------------------------
# Steps
# -----------------------------------------------------------------------------


def extract_report(report_zip: Path, extract_dir: Path) -> None:
    """Unpack the reporter's zip; it must contain html_report/."""
    if not report_zip.is_file():
        raise GenerateError(
            f"Coverage report not found at {report_zip}\n"
            "       Run 'bazel coverage --config=llvm_cov //... --build_tests_only' first."
        )
    if not zipfile.is_zipfile(report_zip):
        raise GenerateError(
            f"{report_zip} is not the LLVM pipeline zip report.\n"
            "       Run 'bazel coverage --config=llvm_cov //... --build_tests_only' first."
        )
    with zipfile.ZipFile(report_zip) as zf:
        zf.extractall(extract_dir)
    if not (extract_dir / "html_report").is_dir():
        raise GenerateError(f"html_report/ not found in {report_zip}")


def run_justifications(
    workspace: Path, yaml_rel: str, platform: str, output_dir: Path, justification_dir: Path
) -> float:
    """Resolve justifications, post-process the HTML and return the effective line coverage."""
    yaml_path = workspace / yaml_rel
    if not yaml_path.is_file():
        raise GenerateError(f"{yaml_path} not found.")
    print("\nRunning coverage justification processing...")
    justification_dir.mkdir(parents=True, exist_ok=True)
    manifest = justification_dir / "manifest.json"
    report = justification_dir / "report.json"
    # In-process calls. Both tools call sys.exit(1) on their own errors; that
    # is turned into a GenerateError so it exits with EXIT_ERROR (2) and can
    # never be mistaken for the gate verdict (0/1).
    _call_tool(
        "justify",
        justify.main,
        ["--yaml", str(yaml_path), "--source-root", str(workspace), "--platform", platform, "--output", str(manifest)],
    )
    _call_tool(
        "effective_coverage",
        effective_coverage.main,
        ["--html-dir", str(output_dir), "--manifest", str(manifest), "--output", str(report)],
    )
    summary_txt = justification_dir / "summary.txt"
    if not summary_txt.is_file():
        raise GenerateError("Effective coverage summary was not produced.")
    print()
    print(summary_txt.read_text(encoding="utf-8"), end="")
    return effective_line_coverage_from_report(report)


def _call_tool(name: str, entry, argv: list[str]) -> None:
    try:
        entry(argv)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise GenerateError(f"{name} failed with exit code {exc.code}") from exc


def write_summary(
    workspace: Path,
    lcov: Path,
    justification_dir: Path | None,
    summary_md: str | None,
    step_summary: str | None,
) -> None:
    """Emit the markdown summary to --summary-md or, failing that, GITHUB_STEP_SUMMARY."""
    args: list[str] = ["--lcov", str(lcov)]
    if justification_dir is not None and (justification_dir / "report.json").is_file():
        args += ["--justification-report", str(justification_dir / "report.json")]
    if summary_md:
        target = Path(summary_md)
        if not target.is_absolute():
            target = workspace / target
        coverage_summary.main(args + ["--output", str(target)])
        print(f"Coverage summary written to: {target}")
    elif step_summary:
        coverage_summary.main(args + ["--output", step_summary, "--append"])
        print("Coverage summary appended to GITHUB_STEP_SUMMARY")


def assemble_artifacts(
    dest: Path,
    workspace: Path,
    testlogs_subdir: str,
    output_dir: Path,
    lcov: Path,
    justification_dir: Path | None,
) -> None:
    """Copy JUnit XMLs (tree preserved), the HTML report, the LCOV and the justification report."""
    dest.mkdir(parents=True, exist_ok=True)
    testlogs = workspace / "bazel-testlogs" / testlogs_subdir if testlogs_subdir else workspace / "bazel-testlogs"
    if not testlogs.is_dir():
        raise GenerateError(f"test logs directory not found: {testlogs}")
    for xml in sorted(testlogs.rglob("test.xml")):
        rel = xml.relative_to(workspace)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(xml, target)
    shutil.copytree(output_dir, dest / output_dir.name, dirs_exist_ok=True)
    if lcov.is_file():
        shutil.copy2(lcov, dest / "coverage_report.dat")
    if justification_dir is not None and justification_dir.is_dir():
        shutil.copytree(justification_dir, dest / justification_dir.name, dirs_exist_ok=True)


# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------


def run(opts: Options, workspace: Path, environ: dict | None = None) -> int:
    """Execute the full flow from ``workspace`` and return the exit code."""
    env = os.environ if environ is None else environ
    threshold = parse_threshold(env.get("COVERAGE_THRESHOLD"))

    output_dir = workspace / (opts.output_dir or f"coverage_{opts.platform}")
    report_zip = workspace / COVERAGE_REPORT_REL

    with tempfile.TemporaryDirectory(prefix="coverage_extract_") as tmp:
        extract_dir = Path(tmp)
        extract_report(report_zip, extract_dir)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        shutil.copytree(extract_dir / "html_report", output_dir)
        print(f"Coverage report written to: {output_dir}")

        lcov = extract_dir / "lcov_report" / "lcov.dat"
        justification_dir: Path | None = None
        if opts.yaml:
            justification_dir = extract_dir / "justification_report"
            gate_pct = run_justifications(workspace, opts.yaml, opts.platform, output_dir, justification_dir)
            gate_kind = "Effective"
        else:
            print("\nINFO: no --yaml given; justification processing skipped, gating on raw line coverage.")
            gate_pct = raw_line_coverage_from_lcov(lcov)
            print(f"Raw line coverage: {gate_pct:.2f}%")
            gate_kind = "Raw"

        # The summary is emitted BEFORE the gate decides, so a failing gate
        # still leaves it on the workflow run page.
        write_summary(workspace, lcov, justification_dir, opts.summary_md, env.get("GITHUB_STEP_SUMMARY"))

        if gate_passes(gate_pct, threshold):
            rc = EXIT_OK
        else:
            print(
                f"ERROR: {gate_kind} coverage {gate_pct:.2f}% is below threshold {threshold:g}%",
                file=sys.stderr,
            )
            rc = EXIT_GATE_FAILED

        if opts.archive_dir:
            archive_dir = workspace / opts.archive_dir
            if archive_dir.exists():
                shutil.rmtree(archive_dir)
            assemble_artifacts(archive_dir, workspace, opts.testlogs_subdir, output_dir, lcov, justification_dir)
            print(f"Coverage artifacts written to: {opts.archive_dir}/")

        if opts.archive:
            tree = workspace / "artifacts"
            if tree.exists():
                shutil.rmtree(tree)
            assemble_artifacts(tree, workspace, opts.testlogs_subdir, output_dir, lcov, justification_dir)
            shutil.make_archive(str(workspace / opts.archive), "zip", root_dir=workspace, base_dir="artifacts")
            shutil.rmtree(tree)
            print(f"Coverage archive written to: {opts.archive}.zip")

    return rc


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    opts = parse_args(argv)
    workspace_env = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if not workspace_env:
        print("ERROR: BUILD_WORKSPACE_DIRECTORY is not set; run this tool via `bazel run`.", file=sys.stderr)
        return EXIT_ERROR
    workspace = Path(workspace_env)
    os.chdir(workspace)
    try:
        return run(opts, workspace)
    except GenerateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
