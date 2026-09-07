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
"""Unit tests for effective_coverage: arithmetic, llvm-cov HTML post-processing and the report."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from score_coverage import effective_coverage as ec


def _row(line: int, status: str, count: str, code: str) -> str:
    """One llvm-cov source table row in the exact shape the module parses."""
    return (
        f"<tr><td class='line-number'><a name='L{line}' href='#L{line}'><pre>{line}</pre></a></td>"
        f"<td class='{status}'><pre>{count}</pre></td>"
        f"<td class='code'><pre>{code}</pre></td></tr>\n"
    )


def _branch(line: int, col: int, true_covered: bool, false_covered: bool) -> str:
    def side(name, covered):
        if covered:
            return f"<span class='None'>{name}</span>: <span class='covered-line'>3</span>"
        return f"<span class='red branch'>{name}</span>: <span class='uncovered-line'>0</span>"

    return (
        f"Branch (<span class='line-number'><a name='L{line}' href='#L{line}'><span>{line}:{col}</span></a></span>): "
        f"[{side('True', true_covered)}, {side('False', false_covered)}]\n"
    )


def _pct_cell(covered: int, total: int, color: str = "red") -> str:
    pct = 100.0 * covered / total if total else 0.0
    return f"<td class='column-entry-{color}'><pre>{pct:>7.2f}% ({covered}/{total})</pre></td>"


def _index_page(files, totals) -> str:
    """Minimal llvm-cov index.html: one row per (path, (fc, ft), (lc, lt), (bc, bt)) plus Totals."""
    rows = []
    for path, func, line, branch in files:
        rows.append(
            f"<tr class='light-row'><td><pre><a href='coverage/{path}.html'>{path}</a></pre></td>"
            f"{_pct_cell(*func)}{_pct_cell(*line)}{_pct_cell(*branch)}</tr>\n"
        )
    func, line, branch = totals
    rows.append(
        f"<tr class='light-row-bold'><td><pre>Totals</pre></td>{_pct_cell(*func)}{_pct_cell(*line)}{_pct_cell(*branch)}</tr>\n"
    )
    return "<html><body><h2>Coverage Report</h2><table>" + "".join(rows) + "</table></body></html>"


class FloorTwoDecimalsTest(unittest.TestCase):
    def test_never_rounds_up(self):
        self.assertEqual(ec.floor_two_decimals(61.7647), 61.76)
        self.assertEqual(ec.floor_two_decimals(99.999), 99.99)
        self.assertEqual(ec.floor_two_decimals(100.0), 100.0)
        self.assertEqual(ec.floor_two_decimals(0.0), 0.0)


class ParseIndexPageTotalsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.html = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_totals_row(self):
        (self.html / "index.html").write_text(
            _index_page([("src/a.cpp", (1, 2), (10, 20), (2, 4))], ((5, 6), (17, 34), (6, 10))), encoding="utf-8"
        )
        totals = ec.parse_index_page_totals(self.html)
        self.assertEqual(totals["lines"], (17, 34))
        self.assertEqual(totals["branches"], (6, 10))

    def test_missing_index_yields_zero_totals_and_warns(self):
        err = io.StringIO()
        with redirect_stderr(err):
            totals = ec.parse_index_page_totals(self.html)
        self.assertEqual(totals, {"lines": (0, 0), "branches": (0, 0)})
        self.assertIn("WARNING", err.getvalue())

    def test_unparseable_index_yields_zero_totals(self):
        (self.html / "index.html").write_text("<html><body>nothing here</body></html>", encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            totals = ec.parse_index_page_totals(self.html)
        self.assertEqual(totals["lines"], (0, 0))


class PathHelpersTest(unittest.TestCase):
    def test_extract_source_path(self):
        html_dir = Path("/r/html")
        self.assertEqual(
            ec.extract_source_path_from_html(Path("/r/html/coverage/src/a.cpp.html"), html_dir), "src/a.cpp"
        )
        self.assertEqual(ec.extract_source_path_from_html(Path("/r/html/src/a.cpp.html"), html_dir), "src/a.cpp")
        self.assertEqual(
            ec.extract_source_path_from_html(Path("/r/html/coverage/home/u/ws/src/a.cpp.html"), html_dir),
            "home/u/ws/src/a.cpp",
        )

    def test_find_source_html_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in [
                "index.html",
                "style.css",
                "coverage/src/a.cpp.html",
                "coverage/src/index.html",
                "coverage/rust/lib.rs.html",
            ]:
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("", encoding="utf-8")
            found = [str(f.relative_to(root)) for f in ec.find_source_html_files(root)]
        self.assertEqual(found, ["coverage/rust/lib.rs.html", "coverage/src/a.cpp.html"])


class FindMatchingJustificationsTest(unittest.TestCase):
    JUSTIFIED = {
        "src/bar.cpp": {"5": {"id": "bar-five"}},
        "lib.rs": {"1": {"id": "lib-one"}},
    }

    def test_exact_and_component_suffix_match(self):
        self.assertEqual(ec.find_matching_justifications("src/bar.cpp", self.JUSTIFIED), {5: {"id": "bar-five"}})
        self.assertEqual(
            ec.find_matching_justifications("home/u/ws/src/bar.cpp", self.JUSTIFIED), {5: {"id": "bar-five"}}
        )
        self.assertEqual(ec.find_matching_justifications("rust/lib.rs", self.JUSTIFIED), {1: {"id": "lib-one"}})

    def test_shorter_html_path_matches_at_component_boundary(self):
        self.assertEqual(ec.find_matching_justifications("bar.cpp", self.JUSTIFIED), {5: {"id": "bar-five"}})

    def test_partial_basename_does_not_match(self):
        # A justification for bar.cpp must never leak into foobar.cpp (would inflate effective coverage).
        self.assertEqual(ec.find_matching_justifications("src/foobar.cpp", self.JUSTIFIED), {})
        self.assertEqual(ec.find_matching_justifications("mylib.rs", self.JUSTIFIED), {})
        self.assertEqual(ec.find_matching_justifications("other/xsrc/bar.cpp", self.JUSTIFIED), {})

    def test_line_keys_become_integers(self):
        result = ec.find_matching_justifications("src/bar.cpp", self.JUSTIFIED)
        self.assertEqual(list(result), [5])


class ProcessHtmlFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.html = Path(self.tmp.name) / "a.cpp.html"
        self.applied = []
        self.stale = []
        self.j = {"id": "j-1", "category": "other", "reason": 'it\'s "fine"'}

    def tearDown(self):
        self.tmp.cleanup()

    def _process(self, content, justifications):
        self.html.write_text(content, encoding="utf-8")
        stats = ec.process_html_file(self.html, justifications, self.applied, self.stale)
        return stats, self.html.read_text(encoding="utf-8")

    def test_no_justifications_leaves_file_untouched(self):
        content = _row(1, "uncovered-line", "0", "x")
        stats, after = self._process(content, {})
        self.assertEqual(stats, {"justified": 0, "stale": 0, "justified_branches": 0})
        self.assertEqual(after, content)

    def test_uncovered_justified_line_is_counted_and_restyled(self):
        content = _row(1, "covered-line", "3", "a") + _row(
            2, "uncovered-line", "0", "<span class='region red'>b</span>"
        )
        stats, after = self._process(content, {2: self.j})
        self.assertEqual(stats["justified"], 1)
        self.assertEqual(stats["stale"], 0)
        self.assertIn(
            "<td class='justified-line' title='Justified [j-1]: it&#39;s &quot;fine&quot;'><pre>J</pre></td>", after
        )
        self.assertIn("class='region justified'", after)
        self.assertNotIn("class='region red'", after)
        self.assertEqual(self.applied, [{"file": "a.cpp", "line": 2, "id": "j-1", "category": "other"}])
        # Line 1 is untouched.
        self.assertIn(_row(1, "covered-line", "3", "a"), after)

    def test_covered_justified_line_is_stale(self):
        content = _row(4, "covered-line", "2", "a")
        stats, after = self._process(content, {4: self.j})
        self.assertEqual(stats["stale"], 1)
        self.assertEqual(stats["justified"], 0)
        self.assertEqual(after, content)
        self.assertEqual(self.stale[0]["line"], 4)
        self.assertEqual(self.stale[0]["id"], "j-1")

    def test_justified_line_not_in_file_is_ignored(self):
        content = _row(1, "uncovered-line", "0", "x")
        stats, _ = self._process(content, {99: self.j})
        self.assertEqual(stats, {"justified": 0, "stale": 0, "justified_branches": 0})
        self.assertEqual(self.applied, [])
        self.assertEqual(self.stale, [])

    def test_covered_in_any_instantiation_counts_as_covered(self):
        content = _row(3, "uncovered-line", "0", "t") + _row(3, "covered-line", "1", "t")
        stats, _ = self._process(content, {3: self.j})
        self.assertEqual(stats["stale"], 1)
        self.assertEqual(stats["justified"], 0)

    def test_uncovered_branch_on_justified_line(self):
        content = _row(5, "covered-line", "3", "if (x)") + _branch(5, 9, True, False)
        stats, after = self._process(content, {5: self.j})
        self.assertEqual(stats["justified_branches"], 1)
        self.assertEqual(stats["stale"], 0)
        self.assertEqual(stats["justified"], 0)  # the line itself is covered
        self.assertIn("class='justified-branch'>False</span>: <span class='justified-line'>0</span>", after)
        self.assertEqual(len(self.applied), 1)

    def test_branch_covered_in_one_instantiation_is_not_justified(self):
        content = _row(5, "covered-line", "3", "if (x)") + _branch(5, 9, True, False) + _branch(5, 9, True, True)
        stats, _ = self._process(content, {5: self.j})
        self.assertEqual(stats["justified_branches"], 0)
        self.assertEqual(stats["stale"], 1)  # covered line, no truly uncovered branch: nothing left to justify

    def test_both_directions_uncovered_count_two_branches(self):
        content = _row(5, "uncovered-line", "0", "if (x)") + _branch(5, 9, False, False)
        stats, _ = self._process(content, {5: self.j})
        self.assertEqual(stats["justified"], 1)
        self.assertEqual(stats["justified_branches"], 2)

    def test_branches_on_unjustified_lines_untouched(self):
        content = _row(5, "covered-line", "3", "if (x)") + _branch(5, 9, True, False)
        stats, after = self._process(content, {7: self.j})
        self.assertEqual(stats["justified_branches"], 0)
        self.assertIn("class='red branch'>False</span>", after)


class UpdateIndexPageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.html = Path(self.tmp.name)
        (self.html / "index.html").write_text(
            _index_page(
                [("src/a.cpp", (1, 2), (5, 10), (1, 4)), ("src/b.cpp", (2, 2), (10, 10), (4, 4))],
                ((3, 4), (15, 20), (5, 8)),
            ),
            encoding="utf-8",
        )
        (self.html / "style.css").write_text("body {}\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_banner_per_file_and_totals_updated(self):
        stats = {
            "total_instrumented_lines": 20,
            "covered_lines": 15,
            "justified_lines": 3,
            "unjustified_uncovered_lines": 2,
            "raw_line_coverage_pct": 75.0,
            "effective_line_coverage_pct": 90.0,
            "total_branches": 8,
            "covered_branches": 5,
            "justified_branches": 1,
            "raw_branch_coverage_pct": 62.5,
            "effective_branch_coverage_pct": 75.0,
        }
        ec.update_index_page(self.html, stats, {"src/a.cpp": {"justified": 3, "stale": 0, "justified_branches": 1}})
        content = (self.html / "index.html").read_text(encoding="utf-8")
        self.assertIn("Effective Line Coverage: 90.0%", content)
        self.assertIn("Effective Branch Coverage: 75.0%", content)
        # per-file row: 5+3 of 10 lines, 1+1 of 4 branches
        self.assertIn("<td class='column-entry-yellow'><pre>  80.00% (8/10)</pre></td>", content)
        self.assertIn("<td class='column-entry-red'><pre>  50.00% (2/4)</pre></td>", content)
        # totals row uses the stats' effective numbers
        self.assertIn("<td class='column-entry-yellow'><pre>  90.00% (18/20)</pre></td>", content)
        self.assertIn("<td class='column-entry-red'><pre>  75.00% (6/8)</pre></td>", content)
        # untouched file keeps its cell
        self.assertIn(_pct_cell(10, 10), content)

    def test_css_injection(self):
        ec.inject_justified_css(self.html)
        css = (self.html / "style.css").read_text(encoding="utf-8")
        self.assertTrue(css.startswith("body {}\n"))
        self.assertIn(".justified-line", css)
        self.assertIn(".justified-branch", css)

    def test_color_thresholds(self):
        self.assertEqual(ec._get_coverage_color(100.0), "green")
        self.assertEqual(ec._get_coverage_color(99.99), "yellow")
        self.assertEqual(ec._get_coverage_color(80.0), "yellow")
        self.assertEqual(ec._get_coverage_color(79.99), "red")


class MainLlvmCovTest(unittest.TestCase):
    """End-to-end on a synthetic llvm-cov report: report.json, summary.txt and HTML edits."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.html = root / "html_report"
        (self.html / "coverage" / "src").mkdir(parents=True)
        (self.html / "index.html").write_text(
            _index_page([("src/a.cpp", (1, 1), (3, 5), (1, 2))], ((1, 1), (3, 5), (1, 2))), encoding="utf-8"
        )
        (self.html / "style.css").write_text("body {}\n", encoding="utf-8")
        (self.html / "coverage" / "src" / "a.cpp.html").write_text(
            _row(1, "covered-line", "1", "a")
            + _row(2, "covered-line", "1", "b")
            + _row(3, "covered-line", "1", "c")
            + _row(4, "uncovered-line", "0", "<span class='region red'>d</span>")
            + _row(5, "uncovered-line", "0", "<span class='region red'>e</span>"),
            encoding="utf-8",
        )
        self.manifest = root / "manifest.json"
        self.report = root / "just" / "report.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, justified_files):
        self.manifest.write_text(json.dumps({"version": 1, "justified_files": justified_files}), encoding="utf-8")
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            ec.main(["--html-dir", str(self.html), "--manifest", str(self.manifest), "--output", str(self.report)])
        return json.loads(self.report.read_text(encoding="utf-8"))

    def test_one_justified_line(self):
        report = self._run({"src/a.cpp": {"4": {"id": "j-4", "category": "other", "reason": "r"}}})
        s = report["summary"]
        self.assertEqual((s["total_instrumented_lines"], s["covered_lines"], s["justified_lines"]), (5, 3, 1))
        self.assertEqual(s["unjustified_uncovered_lines"], 1)
        self.assertEqual(s["raw_line_coverage_pct"], 60.0)
        self.assertEqual(s["effective_line_coverage_pct"], 80.0)
        self.assertEqual(s["total_branches"], 2)
        self.assertEqual(report["applied_justifications"][0]["line"], 4)
        self.assertEqual(report["stale_justifications"], [])
        summary = (self.report.parent / "summary.txt").read_text(encoding="utf-8")
        self.assertIn("Justified lines:          1", summary)
        self.assertIn("Raw line coverage:        60.0%", summary)
        self.assertIn("Effective line coverage:  80.0%", summary)
        index = (self.html / "index.html").read_text(encoding="utf-8")
        self.assertIn("Effective Line Coverage: 80.0%", index)
        self.assertIn("(4/5)", index)
        self.assertIn(".justified-line", (self.html / "style.css").read_text(encoding="utf-8"))
        page = (self.html / "coverage" / "src" / "a.cpp.html").read_text(encoding="utf-8")
        self.assertIn("<pre>J</pre>", page)

    def test_no_justifications_effective_equals_raw(self):
        report = self._run({})
        s = report["summary"]
        self.assertEqual(s["justified_lines"], 0)
        self.assertEqual(s["effective_line_coverage_pct"], s["raw_line_coverage_pct"])

    def test_stale_justification_is_reported_not_counted(self):
        report = self._run({"src/a.cpp": {"1": {"id": "stale-1", "category": "other", "reason": "r"}}})
        s = report["summary"]
        self.assertEqual(s["justified_lines"], 0)
        self.assertEqual(s["stale_justifications"], 1)
        self.assertEqual(s["effective_line_coverage_pct"], 60.0)
        self.assertEqual(report["stale_justifications"][0]["id"], "stale-1")
        summary = (self.report.parent / "summary.txt").read_text(encoding="utf-8")
        self.assertIn("Stale justifications (1):", summary)

    def test_justification_for_other_file_does_not_apply(self):
        report = self._run({"src/foo_a.cpp": {"4": {"id": "x", "category": "other", "reason": "r"}}})
        self.assertEqual(report["summary"]["justified_lines"], 0)

    def test_effective_coverage_is_floored(self):
        # 3 covered + 1 justified of 5 = 80.0 exactly; use 4/5 -> 3 covered of 5 = 60.0; craft 2/3 case instead
        (self.html / "index.html").write_text(
            _index_page([("src/a.cpp", (1, 1), (1, 3), (0, 0))], ((1, 1), (1, 3), (0, 0))), encoding="utf-8"
        )
        report = self._run({"src/a.cpp": {"4": {"id": "j", "category": "other", "reason": "r"}}})
        s = report["summary"]
        self.assertEqual(s["raw_line_coverage_pct"], 33.33)
        self.assertEqual(s["effective_line_coverage_pct"], 66.66)  # 66.666.. floored, never 66.67

    def test_missing_manifest_exits(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                ec.main(
                    [
                        "--html-dir",
                        str(self.html),
                        "--manifest",
                        str(self.manifest / "nope"),
                        "--output",
                        str(self.report),
                    ]
                )

    def test_missing_html_dir_exits(self):
        self.manifest.write_text(json.dumps({"justified_files": {}}), encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                ec.main(
                    [
                        "--html-dir",
                        str(self.html / "missing"),
                        "--manifest",
                        str(self.manifest),
                        "--output",
                        str(self.report),
                    ]
                )


class FormatDetectionAndLcovTest(unittest.TestCase):
    def test_detect_html_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("", encoding="utf-8")
            self.assertEqual(ec.detect_html_format(root), "llvm_cov")
            (root / "index.a_cpp.0123abcd.html").write_text("", encoding="utf-8")
            self.assertEqual(ec.detect_html_format(root), "gcovr")

    def test_parse_lcov_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            lcov = Path(tmp) / "lcov.dat"
            lcov.write_text(
                "SF:a\nLF:10\nLH:4\nBRF:6\nBRH:2\nend_of_record\nSF:b\nLF:5\nLH:5\nend_of_record\n", encoding="utf-8"
            )
            totals = ec._parse_lcov_totals(lcov)
        self.assertEqual(totals, {"lines": (9, 15), "branches": (2, 6)})


if __name__ == "__main__":
    unittest.main()
