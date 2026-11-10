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
"""Retain per-test coverage outputs and their Bazel Build Event Protocol IDs.

The payload is opaque: gcov LCOV and LLVM per-test ZIPs are copied unchanged.
Export immediately after coverage, before another build can replace its outputs.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit


class ExportError(ValueError):
    """The event stream cannot supply an unambiguous measurement export."""


def _object(value: object, context: str) -> dict:
    """Reject malformed event fields with a diagnostic instead of a Python traceback."""
    if not isinstance(value, dict):
        raise ExportError(f"Invalid {context}: expected a JSON object")
    return value


def _test_result(event: dict) -> dict:
    """Validate the fields used for attribution before retaining any measurements."""
    identity = _object(_object(event.get("id", {}), "event id").get("testResult", {}), "test result id")
    configuration = _object(identity.get("configuration", {}), "test configuration")
    if not all(isinstance(value, str) and value for value in (identity.get("label"), configuration.get("id"))):
        raise ExportError("Test result is missing its label or configuration identity")
    for field in ("run", "shard", "attempt"):
        value = identity.get(field, 0)
        if type(value) is not int or value < 0:
            raise ExportError(f"Invalid test result {field}: expected a nonnegative integer")
    result = _object(event["testResult"], "testResult")
    outputs = result.get("testActionOutput", [])
    if not isinstance(outputs, list):
        raise ExportError("Invalid testActionOutput: expected a JSON array")
    for output in outputs:
        _object(output, "testActionOutput entry")
    execution = _object(result.get("executionInfo", {}), "executionInfo")
    if not isinstance(result.get("status", "NO_STATUS"), str):
        raise ExportError("Invalid test status: expected a string")
    for field, source in (("cachedLocally", result), ("cachedRemotely", execution)):
        if not isinstance(source.get(field, False), bool):
            raise ExportError(f"Invalid {field}: expected a boolean")
    return {"id": identity, "result": result}


def read_results(events_file: Path) -> tuple[str, list[dict]]:
    """Read one complete, successful coverage invocation without collapsing runs."""
    started = {}
    finished = {}
    complete = False
    results = {}
    with events_file.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            try:
                event = _object(json.loads(line), f"build event on line {number}")
            except json.JSONDecodeError as exc:
                raise ExportError(f"Invalid build event JSON on line {number}: {exc}") from exc
            if complete:
                raise ExportError("Build events continue after lastMessage")
            complete = event.get("lastMessage", False)
            if not isinstance(complete, bool):
                raise ExportError(f"Invalid lastMessage on line {number}: expected a boolean")
            if "started" in event:
                if started:
                    raise ExportError("Expected one coverage invocation, found multiple build starts")
                started = _object(event["started"], "started")
            if "finished" in event:
                if finished:
                    raise ExportError("Expected one coverage invocation, found multiple build finishes")
                finished = _object(event["finished"], "finished")
            if "testResult" not in event:
                continue
            item = _test_result(event)
            # Protobuf JSON may omit zero-valued fields. Treat explicit zero
            # and an omitted run/shard/attempt alike when detecting duplicate
            # identities, while preserving the original ID in the manifest.
            identity = {**item["id"], **{field: item["id"].get(field, 0) for field in ("run", "shard", "attempt")}}
            key = json.dumps(identity, sort_keys=True)
            if key in results:
                raise ExportError(f"Duplicate test result identity: {key}")
            results[key] = item
    # Protobuf JSON omits scalar defaults: SUCCESS normally has no numeric code.
    if not complete or "exitCode" not in finished:
        raise ExportError("Expected a complete build event stream with a build exit code")
    exit_code = _object(finished["exitCode"], "build exit code").get("code", 0)
    if type(exit_code) is not int:
        raise ExportError("Invalid build exit code: expected an integer")
    if exit_code != 0:
        raise ExportError("Measurement export requires a successful coverage invocation")
    if started.get("command") != "coverage" or not isinstance(started.get("uuid"), str) or not started["uuid"]:
        raise ExportError("Expected build events from one 'bazel coverage' invocation with a UUID")
    if not results:
        raise ExportError("No test results in coverage build events")
    return started["uuid"], [results[key] for key in sorted(results)]


def measurement_bytes(output: dict, retained_paths: set[Path]) -> bytes:
    """Resolve a local BEP file or inline bytes; remote artifacts must be materialized."""
    if "contents" in output:
        if not isinstance(output["contents"], str):
            raise ExportError("Invalid inline coverage artifact: expected base64 text")
        return base64.b64decode(output["contents"], validate=True)
    uri = output.get("uri", "")
    if not isinstance(uri, str):
        raise ExportError("Invalid coverage artifact URI: expected a string")
    location = urlsplit(uri)
    if location.scheme != "file" or location.netloc not in ("", "localhost"):
        raise ExportError(
            "Coverage artifact needs a local file URI or inline contents. Collect with "
            "--remote_download_outputs=all --nobuild_event_json_file_path_conversion."
        )
    path = Path(unquote(location.path))
    if not path.is_absolute() or location.query or location.fragment:
        raise ExportError("Coverage artifact must have an absolute local file URI without query or fragment")
    path = path.resolve()
    # Different attempts may have reused an output location. A post-build
    # snapshot cannot recover overwritten bytes, so do not attribute the same
    # local file to multiple result identities as if each were independently
    # retained. Inline payloads belong directly to their individual events.
    if path in retained_paths:
        raise ExportError(f"Coverage artifact is shared by multiple test results: {path}")
    retained_paths.add(path)
    return path.read_bytes()


def export_measurements(events_file: Path, output: Path) -> None:
    """Atomically publish original measurements with their invocation/test identities."""
    if output.resolve() == events_file.resolve():
        raise ExportError("Output archive must be separate from the build event file")
    invocation, results = read_results(events_file)
    entries = []
    retained_paths: set[Path] = set()
    # Keep an existing export usable if any artifact is unavailable. Staging on
    # the destination filesystem lets publication use one atomic rename.
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        temporary_archive = Path(temporary) / "measurements.zip"
        with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, item in enumerate(results):
                result = item["result"]
                measurements = [file for file in result.get("testActionOutput", []) if file.get("name") == "test.lcov"]
                if len(measurements) > 1:
                    raise ExportError(f"Multiple coverage artifacts for test result {item['id']}")
                measurement = None
                if measurements:
                    data = measurement_bytes(measurements[0], retained_paths)
                    # Labels and source paths can contain separators or refer
                    # to external repositories. Numeric member names preserve
                    # those identities in the manifest without creating paths
                    # that depend on the original checkout layout.
                    path = f"measurements/{index:08d}.dat"
                    archive.writestr(path, data)
                    measurement = {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                entries.append(
                    {
                        "id": item["id"],
                        "status": result.get("status", "NO_STATUS"),
                        "cached_locally": result.get("cachedLocally", False),
                        "cached_remotely": result.get("executionInfo", {}).get("cachedRemotely", False),
                        "measurement": measurement,
                    }
                )
            archive.writestr(
                "manifest.json",
                json.dumps({"version": 1, "invocation_id": invocation, "test_results": entries}, indent=2) + "\n",
            )
        # A mistyped destination must not destroy the measurements being
        # retained, including when the destination aliases a source symlink.
        if output.resolve() in retained_paths:
            raise ExportError("Output archive must be separate from the input coverage artifacts")
        os.replace(temporary_archive, output)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; paths passed via bazel run are relative to the consumer workspace."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-events", type=Path, required=True, help="JSON file from --build_event_json_file")
    parser.add_argument("--output", type=Path, required=True, help="Destination ZIP (parent directory must exist)")
    args = parser.parse_args(argv)
    workspace = Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", "."))
    try:
        export_measurements(workspace / args.build_events, workspace / args.output)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
