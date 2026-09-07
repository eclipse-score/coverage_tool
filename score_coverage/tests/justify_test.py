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
"""Unit tests for justify: YAML validation, marker scanning and manifest generation."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from score_coverage import justify

VALID_ENTRY = {
    "id": "defensive-null-check",
    "category": "defensive_programming",
    "platforms": ["linux"],
    "reason": "Cannot be reached: the pointer is validated by the caller.",
}


def _valid_yaml(**overrides):
    entry = dict(VALID_ENTRY)
    entry.update(overrides)
    return {"version": 1, "justifications": [entry]}


def _validate(data):
    """Run validate_yaml quietly; return None on success or the SystemExit code."""
    with redirect_stderr(io.StringIO()):
        try:
            justify.validate_yaml(data)
        except SystemExit as exc:
            return exc.code
    return None


class ValidateYamlTest(unittest.TestCase):
    def test_valid_document(self):
        self.assertIsNone(_validate(_valid_yaml()))

    def test_valid_with_locations(self):
        locations = [
            {"file": "src/a.cpp", "line": 3},
            {"file": "src/a.cpp", "line_start": 10, "line_end": 12},
            {"file": "src/b.rs", "lines": [1, 2, 3]},
        ]
        self.assertIsNone(_validate(_valid_yaml(locations=locations)))

    def test_empty_justifications_is_valid(self):
        self.assertIsNone(_validate({"version": 1, "justifications": []}))

    def test_root_must_be_mapping(self):
        self.assertEqual(_validate(["not", "a", "mapping"]), 1)
        self.assertEqual(_validate(None), 1)

    def test_version_field(self):
        self.assertEqual(_validate({"justifications": []}), 1)
        self.assertEqual(_validate({"version": "1", "justifications": []}), 1)

    def test_justifications_field(self):
        self.assertEqual(_validate({"version": 1}), 1)
        self.assertEqual(_validate({"version": 1, "justifications": {"a": 1}}), 1)

    def test_entry_shape(self):
        self.assertEqual(_validate({"version": 1, "justifications": ["string"]}), 1)
        entry = dict(VALID_ENTRY)
        del entry["id"]
        self.assertEqual(_validate({"version": 1, "justifications": [entry]}), 1)
        self.assertEqual(_validate(_valid_yaml(id=42)), 1)

    def test_duplicate_ids(self):
        data = {"version": 1, "justifications": [dict(VALID_ENTRY), dict(VALID_ENTRY)]}
        self.assertEqual(_validate(data), 1)

    def test_id_must_be_kebab_case(self):
        for bad in ["Defensive", "has_underscore", "trailing-", "-leading", "double--dash", "with space", ""]:
            with self.subTest(bad=bad):
                self.assertEqual(_validate(_valid_yaml(id=bad)), 1)
        for good in ["a", "a1", "abc-def-123"]:
            with self.subTest(good=good):
                self.assertIsNone(_validate(_valid_yaml(id=good)))

    def test_category(self):
        entry = dict(VALID_ENTRY)
        del entry["category"]
        self.assertEqual(_validate({"version": 1, "justifications": [entry]}), 1)
        self.assertEqual(_validate(_valid_yaml(category=3)), 1)
        self.assertEqual(_validate(_valid_yaml(category="unknown")), 1)
        for cat in sorted(justify.VALID_CATEGORIES):
            with self.subTest(cat=cat):
                self.assertIsNone(_validate(_valid_yaml(category=cat)))

    def test_platforms(self):
        entry = dict(VALID_ENTRY)
        del entry["platforms"]
        self.assertEqual(_validate({"version": 1, "justifications": [entry]}), 1)
        self.assertEqual(_validate(_valid_yaml(platforms="linux")), 1)
        self.assertEqual(_validate(_valid_yaml(platforms=[])), 1)
        self.assertEqual(_validate(_valid_yaml(platforms=[1])), 1)
        self.assertEqual(_validate(_valid_yaml(platforms=["windows"])), 1)
        self.assertIsNone(_validate(_valid_yaml(platforms=["linux", "qnx"])))

    def test_reason(self):
        entry = dict(VALID_ENTRY)
        del entry["reason"]
        self.assertEqual(_validate({"version": 1, "justifications": [entry]}), 1)
        self.assertEqual(_validate(_valid_yaml(reason=5)), 1)
        self.assertEqual(_validate(_valid_yaml(reason="   ")), 1)

    def test_locations(self):
        self.assertEqual(_validate(_valid_yaml(locations={"file": "a"})), 1)
        self.assertEqual(_validate(_valid_yaml(locations=["a"])), 1)
        self.assertEqual(_validate(_valid_yaml(locations=[{"line": 1}])), 1)
        self.assertEqual(_validate(_valid_yaml(locations=[{"file": 1, "line": 1}])), 1)
        self.assertEqual(_validate(_valid_yaml(locations=[{"file": "a", "line": "1"}])), 1)
        self.assertEqual(_validate(_valid_yaml(locations=[{"file": "a", "line_start": "1", "line_end": 2}])), 1)
        self.assertEqual(_validate(_valid_yaml(locations=[{"file": "a", "lines": 3}])), 1)
        self.assertEqual(_validate(_valid_yaml(locations=[{"file": "a", "lines": [1, "2"]}])), 1)

    def test_all_errors_are_reported_together(self):
        err = io.StringIO()
        entry = {"id": "Bad_Id", "category": "nope", "platforms": [], "reason": ""}
        with redirect_stderr(err):
            with self.assertRaises(SystemExit):
                justify.validate_yaml({"version": 1, "justifications": [entry]})
        text = err.getvalue()
        for fragment in ["kebab-case", "invalid category", "must not be empty", "'reason' must not be empty"]:
            self.assertIn(fragment, text)


class ResolveLocationLinesTest(unittest.TestCase):
    def test_explicit_lines(self):
        self.assertEqual(justify.resolve_location_lines({"lines": [3, 1, 2]}), [3, 1, 2])

    def test_range_is_inclusive(self):
        self.assertEqual(justify.resolve_location_lines({"line_start": 10, "line_end": 12}), [10, 11, 12])

    def test_single_line(self):
        self.assertEqual(justify.resolve_location_lines({"line": 7}), [7])

    def test_no_line_information(self):
        self.assertEqual(justify.resolve_location_lines({"file": "a"}), [])

    def test_lines_take_precedence(self):
        self.assertEqual(justify.resolve_location_lines({"lines": [1], "line": 5}), [1])


class MatchesPlatformTest(unittest.TestCase):
    def test_platform_membership(self):
        entry = {"platforms": ["linux"]}
        self.assertTrue(justify._matches_platform(entry, "linux"))
        self.assertFalse(justify._matches_platform(entry, "qnx"))
        self.assertFalse(justify._matches_platform({}, "linux"))


class ScanFileForMarkersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.by_id = {
            "reason-a": {"id": "reason-a", "category": "other", "reason": "  because A  "},
            "reason-b": {"id": "reason-b", "category": "platform_specific", "reason": "because B"},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _scan(self, text):
        path = self.root / "f.cpp"
        path.write_text(text, encoding="utf-8")
        return justify.scan_file_for_markers(path, "f.cpp", self.by_id)

    def test_single_line_marker(self):
        warnings, lines = self._scan("int a;\nfoo(); // COV_JUSTIFIED reason-a\nint b;\n")
        self.assertEqual(warnings, [])
        self.assertEqual(lines, {2: {"id": "reason-a", "category": "other", "reason": "because A"}})

    def test_region_excludes_marker_lines(self):
        text = "a\n// COV_JUSTIFIED_START reason-b\nx\ny\n// COV_JUSTIFIED_STOP\nz\n"
        warnings, lines = self._scan(text)
        self.assertEqual(warnings, [])
        self.assertEqual(sorted(lines), [3, 4])
        self.assertTrue(all(v["id"] == "reason-b" for v in lines.values()))

    def test_empty_region_justifies_nothing(self):
        warnings, lines = self._scan("// COV_JUSTIFIED_START reason-a\n// COV_JUSTIFIED_STOP\n")
        self.assertEqual(warnings, [])
        self.assertEqual(lines, {})

    def test_nested_regions_inner_wins(self):
        text = (
            "// COV_JUSTIFIED_START reason-a\n"  # 1
            "a\n"  # 2 -> reason-a
            "// COV_JUSTIFIED_START reason-b\n"  # 3
            "b\n"  # 4 -> reason-b, then overwritten by outer STOP? No: outer range re-assigns.
            "// COV_JUSTIFIED_STOP\n"  # 5
            "c\n"  # 6 -> reason-a
            "// COV_JUSTIFIED_STOP\n"  # 7
        )
        warnings, lines = self._scan(text)
        self.assertEqual(warnings, [])
        self.assertEqual(sorted(lines), [2, 3, 4, 5, 6])
        # The outer region is closed last and covers lines 2..6, so it overwrites the inner assignment.
        self.assertEqual(lines[4]["id"], "reason-a")

    def test_unknown_ids_warn_and_do_not_justify(self):
        text = "x // COV_JUSTIFIED nope\n// COV_JUSTIFIED_START nope2\ny\n// COV_JUSTIFIED_STOP\n"
        warnings, lines = self._scan(text)
        self.assertEqual(lines, {})
        self.assertEqual(len(warnings), 3)
        self.assertIn("f.cpp:1: COV_JUSTIFIED references unknown ID 'nope'", warnings[0])
        self.assertIn("f.cpp:2: COV_JUSTIFIED_START references unknown ID 'nope2'", warnings[1])
        self.assertIn("f.cpp:4: COV_JUSTIFIED_STOP without matching START", warnings[2])

    def test_unclosed_region_warns(self):
        warnings, lines = self._scan("// COV_JUSTIFIED_START reason-a\nx\n")
        self.assertEqual(lines, {})
        self.assertEqual(warnings, ["f.cpp:1: COV_JUSTIFIED_START 'reason-a' without matching STOP"])

    def test_stop_without_start_warns(self):
        warnings, lines = self._scan("x\n// COV_JUSTIFIED_STOP\n")
        self.assertEqual(lines, {})
        self.assertEqual(warnings, ["f.cpp:2: COV_JUSTIFIED_STOP without matching START"])

    def test_marker_id_characters(self):
        warnings, lines = self._scan("x // COV_JUSTIFIED reason-a; trailing text\n")
        self.assertEqual(sorted(lines), [1])

    def test_unreadable_file_yields_nothing(self):
        warnings, lines = justify.scan_file_for_markers(self.root / "missing.cpp", "missing.cpp", self.by_id)
        self.assertEqual((warnings, lines), ([], {}))

    def test_non_utf8_content_is_tolerated(self):
        path = self.root / "f.cpp"
        path.write_bytes(b"\xff\xfe junk\nfoo(); // COV_JUSTIFIED reason-a\n")
        warnings, lines = justify.scan_file_for_markers(path, "f.cpp", self.by_id)
        self.assertEqual(sorted(lines), [2])


class CollectSourceFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in ["src/a.cpp", "src/b.h", "src/c.rs", "src/d.py", "bazel-out/e.cpp", "bazel-bin/f.rs", "docs/g.hpp"]:
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _rel(self, files):
        return sorted(str(f.relative_to(self.root)) for f in files)

    def test_default_filter_and_bazel_dirs_skipped(self):
        files = justify.collect_source_files(self.root, "cpp,h,hpp,cc,rs")
        self.assertEqual(self._rel(files), ["docs/g.hpp", "src/a.cpp", "src/b.h", "src/c.rs"])

    def test_custom_filter(self):
        files = justify.collect_source_files(self.root, "py, rs")
        self.assertEqual(self._rel(files), ["src/c.rs", "src/d.py"])

    def test_empty_filter_uses_defaults(self):
        files = justify.collect_source_files(self.root, "")
        self.assertIn("src/a.cpp", self._rel(files))
        self.assertNotIn("src/d.py", self._rel(files))


class LoadYamlTest(unittest.TestCase):
    def test_missing_file_exits(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                justify.load_yaml(Path("/nonexistent/justifications.yaml"))

    def test_loads_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "j.yaml"
            path.write_text("version: 1\njustifications: []\n", encoding="utf-8")
            self.assertEqual(justify.load_yaml(path), {"version": 1, "justifications": []})


class MainTest(unittest.TestCase):
    """End-to-end: YAML locations + in-code markers -> manifest."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "a.cpp").write_text(
            "int a;\nfoo(); // COV_JUSTIFIED marker-linux\nbar(); // COV_JUSTIFIED marker-qnx\nbaz();\n",
            encoding="utf-8",
        )
        (self.root / "src" / "b.rs").write_text("fn b() {}\nfn c() {}\n", encoding="utf-8")
        self.yaml = self.root / "j.yaml"
        self.yaml.write_text(
            "\n".join(
                [
                    "version: 1",
                    "justifications:",
                    "  - id: marker-linux",
                    "    category: defensive_programming",
                    "    platforms: [linux]",
                    "    reason: linux only marker",
                    "  - id: marker-qnx",
                    "    category: platform_specific",
                    "    platforms: [qnx]",
                    "    reason: qnx only marker",
                    "  - id: yaml-loc",
                    "    category: other",
                    "    platforms: [linux, qnx]",
                    "    reason: '  located via yaml  '",
                    "    locations:",
                    "      - file: src/b.rs",
                    "        line_start: 1",
                    "        line_end: 2",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.out = self.root / "out" / "manifest.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, platform):
        argv = ["--yaml", str(self.yaml), "--source-root", str(self.root), "--output", str(self.out)]
        if platform:
            argv += ["--platform", platform]
        err = io.StringIO()
        code = None
        with redirect_stderr(err):
            try:
                justify.main(argv)
            except SystemExit as exc:
                code = exc.code
        manifest = json.loads(self.out.read_text(encoding="utf-8")) if self.out.exists() else None
        return code, manifest, err.getvalue()

    def test_linux_manifest(self):
        code, manifest, err = self._run("linux")
        self.assertIsNone(code)
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["source_root"], str(self.root))
        self.assertEqual(sorted(manifest["justified_files"]), ["src/a.cpp", "src/b.rs"])
        a = manifest["justified_files"]["src/a.cpp"]
        self.assertEqual(list(a), ["2"])  # the qnx-only marker is filtered out; keys are strings
        self.assertEqual(
            a["2"], {"id": "marker-linux", "category": "defensive_programming", "reason": "linux only marker"}
        )
        b = manifest["justified_files"]["src/b.rs"]
        self.assertEqual(sorted(b), ["1", "2"])
        self.assertEqual(b["1"]["reason"], "located via yaml")
        # The filtered-out marker is reported as unknown for this platform.
        self.assertTrue(any("marker-qnx" in w for w in manifest["warnings"]))
        self.assertEqual(manifest["errors"], [])
        self.assertIn("Resolved 3 justified lines across 2 files", err)

    def test_qnx_manifest(self):
        code, manifest, _ = self._run("qnx")
        self.assertIsNone(code)
        self.assertEqual(list(manifest["justified_files"]["src/a.cpp"]), ["3"])

    def test_no_platform_keeps_all(self):
        code, manifest, _ = self._run(None)
        self.assertIsNone(code)
        self.assertEqual(sorted(manifest["justified_files"]["src/a.cpp"]), ["2", "3"])

    def test_missing_location_file_is_an_error(self):
        self.yaml.write_text(
            "version: 1\njustifications:\n  - id: gone\n    category: other\n    platforms: [linux]\n"
            "    reason: r\n    locations:\n      - file: src/missing.cpp\n        line: 1\n",
            encoding="utf-8",
        )
        code, manifest, err = self._run("linux")
        self.assertEqual(code, 1)
        self.assertIn("File not found for justification 'gone'", err)
        self.assertEqual(len(manifest["errors"]), 1)  # the manifest is still written for diagnosis

    def test_invalid_yaml_exits_before_scanning(self):
        self.yaml.write_text("version: 1\n", encoding="utf-8")
        code, manifest, _ = self._run("linux")
        self.assertEqual(code, 1)
        self.assertIsNone(manifest)

    def test_bazel_symlinks_are_not_scanned(self):
        (self.root / "bazel-out").mkdir()
        (self.root / "bazel-out" / "gen.cpp").write_text("x // COV_JUSTIFIED marker-linux\n", encoding="utf-8")
        code, manifest, _ = self._run("linux")
        self.assertIsNone(code)
        self.assertNotIn("bazel-out/gen.cpp", manifest["justified_files"])


if __name__ == "__main__":
    unittest.main()
