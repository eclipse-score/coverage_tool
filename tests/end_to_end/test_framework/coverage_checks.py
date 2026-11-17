# Copyright (c) 2026 Contributors to the Eclipse Foundation
#
# SPDX-License-Identifier: Apache-2.0

"""Read the small CHECK notation used by annotated C++ coverage fixtures."""

import re
from dataclasses import dataclass

# Keep the notation intentionally limited: one literal count per comment,
# with an optional expected failure for one of the two supported backends.
_CHECK = re.compile(
    r"\s*// CHECK (?P<run>[a-z][a-z0-9_]*): "
    r"(?P<metric>line_hits|branch_hits) == (?P<hits>\d+)"
    r"(?: \[xfail: (?P<backend>llvm|gcov)\])?\s*"
)
# Preserve ordinary C++ string/character literals so a URL or "//" in a string
# cannot hide a code line when comments are removed.
_COMMENT_OR_LITERAL = re.compile(
    r'"(?:\\.|[^"\\])*"'
    r"|'(?:\\.|[^'\\])*'"
    r"|//[^\n]*|/\*.*?\*/",
    re.DOTALL,
)


@dataclass(frozen=True)
class CoverageCheck:
    """An expected counter in one report, bound to its following C++ code line."""

    source: str
    line: int
    test_run: str
    metric: str
    expected_hits: int
    xfail_backend: str | None = None

    @property
    def test_id(self) -> str:
        """Identify the assertion in pytest output without depending on declaration order."""
        return f"{self.source}:{self.line}-{self.test_run}-{self.metric}"


def parse_coverage_checks(source: str, text: str) -> list[CoverageCheck]:
    """Bind standalone CHECKs to the next code line; malformed or orphaned CHECKs are errors."""
    # Preserve line numbers while removing both kinds of C++ comments. Blank
    # lines and explanatory comments between CHECKs do not consume a check.
    code = _COMMENT_OR_LITERAL.sub(
        lambda token: "\n" * token[0].count("\n") if token[0].startswith("/") else token[0], text
    )
    code_lines = {number for number, line in enumerate(code.splitlines(), 1) if line.strip()}
    checks = []
    pending = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("// CHECK"):
            match = _CHECK.fullmatch(line)
            if match is None:
                raise ValueError(f"{source}:{number}: malformed coverage CHECK: {line.strip()}")
            pending.append((number, match))
        if number not in code_lines:
            continue
        seen = set()
        for annotation_line, match in pending:
            key = (match["run"], match["metric"])
            if key in seen:
                raise ValueError(f"{source}:{annotation_line}: duplicate CHECK for {key} on code line {number}")
            seen.add(key)
            checks.append(
                CoverageCheck(
                    source=source,
                    line=number,
                    test_run=match["run"],
                    metric=match["metric"],
                    expected_hits=int(match["hits"]),
                    xfail_backend=match["backend"],
                )
            )
        pending.clear()
    if pending:
        raise ValueError(f"{source}:{pending[0][0]}: CHECK has no following code line")
    if not checks:
        raise ValueError(f"{source}: no coverage CHECKs found")
    return checks
