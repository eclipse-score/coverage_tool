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
"""Structural-coverage gate for score_coverage's OWN Python code.

The pipeline this repository ships measures C++ and Rust; its own code is
Python and is measured by coverage.py through `bazel coverage` (rules_python,
configure_coverage_tool = True). This script reads the combined LCOV that
Bazel writes, prints the per-file C0 (line) and C1 (branch) table the
verification report needs, and fails when the totals are below the thresholds.

Usage:
    bazel coverage --combined_report=lcov //score_coverage/tests:all
    bazel run //tools:self_coverage_gate -- --min-lines 69 --min-branches 63 \\
        [--lcov bazel-out/_coverage/_coverage_report.dat] [--summary-md out.md]

Only files under score_coverage/ (excluding tests/) count.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

DEFAULT_LCOV = Path("bazel-out/_coverage/_coverage_report.dat")
SCOPE_PREFIX = "score_coverage/"
EXCLUDED_PREFIX = "score_coverage/tests/"


@dataclass
class FileCoverage:
    path: str
    lines_found: int = 0
    lines_hit: int = 0
    branches_found: int = 0
    branches_hit: int = 0

    def add(self, other: "FileCoverage") -> None:
        self.lines_found += other.lines_found
        self.lines_hit += other.lines_hit
        self.branches_found += other.branches_found
        self.branches_hit += other.branches_hit


@dataclass
class Totals:
    files: List[FileCoverage] = field(default_factory=list)

    @property
    def lines_found(self) -> int:
        return sum(f.lines_found for f in self.files)

    @property
    def lines_hit(self) -> int:
        return sum(f.lines_hit for f in self.files)

    @property
    def branches_found(self) -> int:
        return sum(f.branches_found for f in self.files)

    @property
    def branches_hit(self) -> int:
        return sum(f.branches_hit for f in self.files)


def pct(hit: int, found: int) -> Optional[float]:
    """Percentage, or None when nothing was found (no verdict)."""
    return None if found == 0 else 100.0 * hit / found


def in_scope(path: str) -> bool:
    return path.startswith(SCOPE_PREFIX) and not path.startswith(EXCLUDED_PREFIX)


def parse_lcov(path: Path) -> Totals:
    """Aggregate LF/LH/BRF/BRH per in-scope source file (records may repeat per test)."""
    if not path.is_file():
        raise FileNotFoundError(f"LCOV file not found: {path}")
    per_file: Dict[str, FileCoverage] = {}
    current: Optional[FileCoverage] = None
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("SF:"):
                current = FileCoverage(path=line[3:])
            elif line == "end_of_record":
                if current is not None and in_scope(current.path):
                    per_file.setdefault(current.path, FileCoverage(path=current.path)).add(current)
                current = None
            elif current is not None:
                key, _, value = line.partition(":")
                if key in ("LF", "LH", "BRF", "BRH"):
                    number = int(value)
                    if number < 0:
                        raise ValueError(f"negative {key} in record for {current.path}")
                    attr = {"LF": "lines_found", "LH": "lines_hit", "BRF": "branches_found", "BRH": "branches_hit"}[key]
                    setattr(current, attr, getattr(current, attr) + number)
    for fc in per_file.values():
        if fc.lines_hit > fc.lines_found or fc.branches_hit > fc.branches_found:
            raise ValueError(f"corrupt LCOV record for {fc.path}: hit count exceeds found count")
    return Totals(files=sorted(per_file.values(), key=lambda fc: fc.path))


def fmt(value: Optional[float]) -> str:
    return "  n/a " if value is None else f"{value:6.2f}"


def render_table(totals: Totals, markdown: bool) -> str:
    rows = [(f.path, f.lines_hit, f.lines_found, f.branches_hit, f.branches_found) for f in totals.files]
    rows.append(("TOTAL", totals.lines_hit, totals.lines_found, totals.branches_hit, totals.branches_found))
    if markdown:
        out = ["| File | Lines (C0) | Branches (C1) |", "|---|---:|---:|"]
        for path, lh, lf, bh, bf in rows:
            out.append(
                f"| `{path}` | {fmt(pct(lh, lf)).strip()}% ({lh}/{lf}) | {fmt(pct(bh, bf)).strip()}% ({bh}/{bf}) |"
            )
        return "\n".join(out) + "\n"
    width = max(len(r[0]) for r in rows)
    out = [f"{'File':<{width}}  {'Lines (C0)':>22}  {'Branches (C1)':>22}"]
    for path, lh, lf, bh, bf in rows:
        out.append(f"{path:<{width}}  {fmt(pct(lh, lf))}% ({lh:>4}/{lf:>4})  {fmt(pct(bh, bf))}% ({bh:>4}/{bf:>4})")
    return "\n".join(out) + "\n"


def evaluate(totals: Totals, min_lines: float, min_branches: float) -> List[str]:
    """Return the list of gate violations (empty when the gate passes)."""
    problems = []
    line_pct = pct(totals.lines_hit, totals.lines_found)
    branch_pct = pct(totals.branches_hit, totals.branches_found)
    if line_pct is None:
        problems.append("no instrumented lines found in scope; nothing to gate on")
    elif line_pct < min_lines:
        problems.append(f"line coverage {line_pct:.2f}% is below the minimum of {min_lines:g}%")
    if branch_pct is None:
        problems.append("no branch data found in scope; nothing to gate on")
    elif branch_pct < min_branches:
        problems.append(f"branch coverage {branch_pct:.2f}% is below the minimum of {min_branches:g}%")
    return problems


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lcov", type=Path, default=None, help=f"Combined LCOV (default: {DEFAULT_LCOV})")
    parser.add_argument("--min-lines", type=float, required=True, help="Minimum line coverage in percent")
    parser.add_argument("--min-branches", type=float, required=True, help="Minimum branch coverage in percent")
    parser.add_argument("--summary-md", type=Path, default=None, help="Append a markdown table to this file")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    workspace = Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", "."))
    lcov = args.lcov if args.lcov is not None else workspace / DEFAULT_LCOV
    if not lcov.is_absolute():
        lcov = workspace / lcov
    for threshold in (args.min_lines, args.min_branches):
        if not 0.0 <= threshold <= 100.0:
            print(f"ERROR: thresholds must be within [0, 100], got {threshold}", file=sys.stderr)
            return 2
    try:
        totals = parse_lcov(lcov)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(render_table(totals, markdown=False))
    if args.summary_md is not None:
        target = args.summary_md if args.summary_md.is_absolute() else workspace / args.summary_md
        with open(target, "a", encoding="utf-8") as f:
            f.write("## Structural coverage of score_coverage (coverage.py)\n\n")
            f.write(render_table(totals, markdown=True))
    problems = evaluate(totals, args.min_lines, args.min_branches)
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
