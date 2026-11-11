#!/usr/bin/env python3
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

"""Tests for shared report archive behavior."""
# pylint: disable=missing-function-docstring,missing-class-docstring,consider-using-with

import tempfile
import unittest
import zipfile
from pathlib import Path

from score_coverage import report_archive
from tests.unit.score_coverage.traceability import verifies


@verifies("tool_req__coverage_report_outputs")
class WriteEmptyOutputTest(unittest.TestCase):
    def test_produces_valid_empty_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.zip"
            report_archive.write_empty_output(out)
            self.assertTrue(zipfile.is_zipfile(out))
            with zipfile.ZipFile(out) as zf:
                self.assertEqual(zf.namelist(), [])


@verifies("tool_req__coverage_merge_profraw")
class CreateZipTest(unittest.TestCase):
    def test_only_listed_directories_relative_to_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a" / "sub").mkdir(parents=True)
            (root / "a" / "sub" / "f.txt").write_text("f", encoding="utf-8")
            (root / "b").mkdir()
            (root / "b" / "g.txt").write_text("g", encoding="utf-8")
            (root / "c").mkdir()
            (root / "c" / "h.txt").write_text("h", encoding="utf-8")
            out = root / "out.zip"
            report_archive.create_zip(root, [root / "a", root / "b", root / "missing"], out)
            with zipfile.ZipFile(out) as zf:
                self.assertEqual(sorted(zf.namelist()), ["a/sub/f.txt", "b/g.txt"])
