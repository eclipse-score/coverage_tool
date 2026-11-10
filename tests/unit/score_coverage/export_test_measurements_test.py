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
"""Per-test retention preserves attribution, opaque bytes and missing-data states."""
# pylint: disable=missing-function-docstring,missing-class-docstring,consider-using-with
# pylint: disable=too-many-instance-attributes

import base64
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from score_coverage import export_test_measurements as exporter
from tests.unit.score_coverage.traceability import verifies


@verifies("tool_req__coverage_test_measurements", derivation="design-analysis")
class ExportMeasurementsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.events = self.root / "events.json"
        self.output = self.root / "measurements.zip"
        # Spaces, '#' and non-ASCII characters exercise BEP file URI decoding.
        self.artifact = self.root / "opaque # ü.dat"
        self.artifact.write_bytes(b"SF:src/a.cpp\nDA:1,3\nend_of_record\n")

    def tearDown(self):
        self.tmp.cleanup()

    def result(self, *, identity=None, files=None, **payload):
        return {
            "id": {
                "testResult": identity
                or {
                    "label": "@@external+//pkg:test",
                    "configuration": {"id": "config-a"},
                    "run": 1,
                    "shard": 1,
                    "attempt": 1,
                }
            },
            "testResult": {
                "status": "PASSED",
                "testActionOutput": files
                if files is not None
                else [
                    {
                        "name": "test.lcov",
                        "uri": self.artifact.as_uri(),
                    }
                ],
                **payload,
            },
        }

    def write_events(self, results, *, success=True, complete=True):
        events = [
            {"started": {"uuid": "invocation-a", "command": "coverage"}},
            *results,
            {"finished": {"exitCode": {} if success else {"code": 1}}},
        ]
        if complete:
            events.append({"lastMessage": True})
        self.events.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")

    def manifest(self):
        with zipfile.ZipFile(self.output) as archive:
            return json.loads(archive.read("manifest.json"))

    def test_preserves_identity_and_original_bytes_without_parsing_coverage(self):
        """The same exporter retains gcov LCOV and LLVM ZIP payloads byte for byte."""
        llvm_zip = io.BytesIO()
        with zipfile.ZipFile(llvm_zip, "w") as archive:
            archive.writestr("profdata/target.profdata", b"opaque profile")
            archive.writestr("meta/meta.json", '{"object_files": ["/build/test"]}')
        for data in (self.artifact.read_bytes(), llvm_zip.getvalue(), b""):
            with self.subTest(data=data):
                self.artifact.write_bytes(data)
                event = self.result(cachedLocally=True, executionInfo={"cachedRemotely": True})
                self.write_events([event])
                exporter.export_measurements(self.events, self.output)
                manifest = self.manifest()
                self.assertEqual(manifest["version"], 1)
                self.assertEqual(manifest["invocation_id"], "invocation-a")
                (entry,) = manifest["test_results"]
                self.assertEqual(entry["id"], event["id"]["testResult"])
                self.assertTrue(entry["cached_locally"])
                self.assertTrue(entry["cached_remotely"])
                self.assertEqual(entry["status"], "PASSED")
                self.assertEqual(entry["measurement"]["size"], len(data))
                self.assertEqual(entry["measurement"]["sha256"], hashlib.sha256(data).hexdigest())
                with zipfile.ZipFile(self.output) as archive:
                    self.assertEqual(archive.read(entry["measurement"]["path"]), data)

    def test_runs_shards_attempts_and_configurations_are_not_collapsed(self):
        """A test label is insufficient to distinguish its individual measurements."""
        first = self.result()["id"]["testResult"]
        identities = [first] + [{**first, field: 2} for field in ("run", "shard", "attempt")]
        identities.append({**first, "configuration": {"id": "config-b"}})
        events = []
        for number, identity in enumerate(reversed(identities)):
            artifact = self.root / f"run-{number}.dat"
            artifact.write_bytes(self.artifact.read_bytes())
            events.append(self.result(identity=identity, files=[{"name": "test.lcov", "uri": artifact.as_uri()}]))
        self.write_events(events)
        exporter.export_measurements(self.events, self.output)
        entries = self.manifest()["test_results"]
        self.assertCountEqual([entry["id"] for entry in entries], identities)
        self.assertEqual(len({entry["measurement"]["path"] for entry in entries}), 5)

    def test_unreported_measurement_is_distinct_from_an_empty_artifact(self):
        self.write_events([self.result(files=[{"name": "test.log", "uri": "file:///irrelevant"}])])
        exporter.export_measurements(self.events, self.output)
        (entry,) = self.manifest()["test_results"]
        self.assertIsNone(entry["measurement"])
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.namelist(), ["manifest.json"])

    def test_inline_measurement_is_retained(self):
        data = b"inline LCOV"
        self.write_events(
            [
                self.result(
                    files=[
                        {
                            "name": "test.lcov",
                            "contents": base64.b64encode(data).decode(),
                        }
                    ]
                )
            ]
        )
        exporter.export_measurements(self.events, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read("measurements/00000000.dat"), data)

    def test_reused_output_path_is_rejected_instead_of_inventing_attempt_measurements(self):
        """One remaining file cannot recover distinct bytes from overwritten attempts."""
        first = self.result()
        second = self.result(identity={**first["id"]["testResult"], "attempt": 2})
        self.write_events([first, second])
        self.output.write_bytes(b"previous export")
        with self.assertRaisesRegex(exporter.ExportError, "shared by multiple"):
            exporter.export_measurements(self.events, self.output)
        self.assertEqual(self.output.read_bytes(), b"previous export")

    def test_unavailable_artifact_does_not_replace_existing_export(self):
        """Unfetched remote outputs and deleted local outputs are errors, not measured zero."""
        for uri in ("bytestream://cache/blob", (self.root / "missing.dat").as_uri(), "file://remote/a"):
            with self.subTest(uri=uri):
                self.output.write_bytes(b"previous export")
                self.write_events([self.result(files=[{"name": "test.lcov", "uri": uri}])])
                with self.assertRaises((exporter.ExportError, OSError)):
                    exporter.export_measurements(self.events, self.output)
                self.assertEqual(self.output.read_bytes(), b"previous export")
                self.assertEqual(
                    sorted(path.name for path in self.root.iterdir()),
                    sorted([self.events.name, self.artifact.name, self.output.name]),
                )

    def test_incomplete_failed_and_ambiguous_streams_are_rejected(self):
        for results, options in (
            ([self.result()], {"complete": False}),
            ([self.result()], {"success": False}),
            ([], {}),
            ([self.result(), self.result()], {}),
            ([self.result(identity={"label": "//test"})], {}),
            ([self.result(files=[{"name": "test.lcov"}, {"name": "test.lcov"}])], {}),
        ):
            with self.subTest(results=results, options=options):
                self.write_events(results, **options)
                with self.assertRaises(exporter.ExportError):
                    exporter.export_measurements(self.events, self.output)
                self.assertFalse(self.output.exists())

    def test_cli_resolves_paths_against_consumer_workspace(self):
        self.write_events([self.result()])
        with mock.patch.dict("os.environ", {"BUILD_WORKSPACE_DIRECTORY": str(self.root)}):
            code = exporter.main(["--build-events", self.events.name, "--output", self.output.name])
        self.assertEqual(code, 0)
        self.assertEqual(self.manifest()["invocation_id"], "invocation-a")

    def test_cli_reports_invalid_json_without_replacing_an_archive(self):
        self.events.write_text("not JSON\n", encoding="utf-8")
        self.output.write_bytes(b"previous export")
        error = io.StringIO()
        with redirect_stderr(error):
            code = exporter.main(["--build-events", str(self.events), "--output", str(self.output)])
        self.assertEqual(code, 2)
        self.assertIn("line 1", error.getvalue())
        self.assertEqual(self.output.read_bytes(), b"previous export")

    def test_cli_reports_malformed_event_fields_without_replacing_an_archive(self):
        """A readable JSON file can still be invalid BEP; report the field, not a traceback."""
        self.write_events([self.result()])
        valid = [json.loads(line) for line in self.events.read_text().splitlines()]
        for path, value in (
            ((0,), []),
            ((0, "started"), None),
            ((0, "started", "uuid"), 123),
            ((1, "id"), None),
            ((1, "id", "testResult"), []),
            ((1, "id", "testResult", "configuration"), None),
            ((1, "id", "testResult", "label"), 123),
            ((1, "id", "testResult", "run"), True),
            ((1, "testResult"), []),
            ((1, "testResult", "testActionOutput"), None),
            ((1, "testResult", "testActionOutput"), [None]),
            ((1, "testResult", "executionInfo"), None),
            ((1, "testResult", "status"), 123),
            ((1, "testResult", "cachedLocally"), "false"),
            ((1, "testResult", "testActionOutput", 0, "uri"), None),
            ((1, "testResult", "testActionOutput", 0), {"name": "test.lcov", "contents": None}),
            ((2, "finished"), None),
            ((2, "finished", "exitCode"), []),
            ((2, "finished", "exitCode", "code"), "0"),
            ((3, "lastMessage"), "false"),
        ):
            with self.subTest(field=path):
                events = json.loads(json.dumps(valid))
                parent = events
                for field in path[:-1]:
                    parent = parent[field]
                parent[path[-1]] = value
                self.events.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
                self.output.write_bytes(b"previous export")
                error = io.StringIO()
                with redirect_stderr(error):
                    code = exporter.main(["--build-events", str(self.events), "--output", str(self.output)])
                self.assertEqual(code, 2)
                self.assertTrue(error.getvalue().startswith("ERROR:"), error.getvalue())
                self.assertEqual(self.output.read_bytes(), b"previous export")

    def test_protobuf_default_identity_fields_do_not_disguise_a_duplicate(self):
        """Omitted scalar IDs and explicit zero encode the same protobuf identity."""
        first = self.result()
        first["id"]["testResult"].pop("run")
        second = self.result(identity={**first["id"]["testResult"], "run": 0})
        self.write_events([first, second])
        with self.assertRaisesRegex(exporter.ExportError, "Duplicate test result identity"):
            exporter.export_measurements(self.events, self.output)

    def test_stream_must_describe_one_finished_coverage_invocation(self):
        self.write_events([self.result()])
        valid = [json.loads(line) for line in self.events.read_text().splitlines()]
        for events in (
            [valid[0], *valid],
            [*valid[:-1], valid[-2], valid[-1]],
            [*valid, valid[0]],
            [{"started": {"uuid": "invocation-a", "command": "test"}}, *valid[1:]],
        ):
            with self.subTest(events=events):
                self.events.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
                with self.assertRaises(exporter.ExportError):
                    exporter.export_measurements(self.events, self.output)
                self.assertFalse(self.output.exists())

    def test_relative_or_qualified_local_uri_is_rejected(self):
        """An artifact location must identify an absolute file, without URL query semantics."""
        for uri in ("file:relative.dat", self.artifact.as_uri() + "?query", self.artifact.as_uri() + "#fragment"):
            with self.subTest(uri=uri):
                self.write_events([self.result(files=[{"name": "test.lcov", "uri": uri}])])
                with self.assertRaisesRegex(exporter.ExportError, "absolute local file URI"):
                    exporter.export_measurements(self.events, self.output)
                self.assertFalse(self.output.exists())

    def test_output_cannot_overwrite_its_own_inputs(self):
        """Keep the BEP and measurement usable when the output path aliases either input."""
        self.write_events([self.result()])
        alias = self.root / "artifact-alias.dat"
        alias.symlink_to(self.artifact)
        for destination in (self.events, self.artifact, alias):
            with self.subTest(destination=destination):
                original = destination.read_bytes()
                with self.assertRaisesRegex(exporter.ExportError, "Output archive must be separate"):
                    exporter.export_measurements(self.events, destination)
                self.assertEqual(destination.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
