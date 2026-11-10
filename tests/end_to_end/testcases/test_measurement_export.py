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
"""Retain real test measurements with identities supplied by Bazel, including cache hits."""

import hashlib
import io
import json
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from _blackbox_support import run_bazel, verifies


@pytest.mark.parametrize("backend", ["llvm_cov", "gcov"])
@verifies("tool_req__coverage_test_measurements")
def test_export_retains_each_test_run_and_cached_measurement(
    consumer_workspace: Path, tmp_path: Path, backend: str
) -> None:
    """Two runs per test remain separate; exporting cached data needs no new test execution."""
    events = tmp_path / "events.json"
    output = tmp_path / "measurements.zip"
    targets = ["//src:coverable_test", "//lib/test:cross_pkg_test"]
    coverage = [
        "coverage",
        f"--config={backend}",
        *targets,
        "--runs_per_test=2",
        "--cache_test_results=yes",
        "--nobuild_event_json_file_path_conversion",
        f"--build_event_json_file={events}",
    ]
    run_bazel(consumer_workspace, coverage)
    run_bazel(consumer_workspace, coverage)
    run_bazel(
        consumer_workspace,
        [
            "run",
            "@score_coverage//:export_test_measurements",
            "--",
            "--build-events",
            str(events),
            "--output",
            str(output),
        ],
    )
    result_events = [event for line in events.read_text().splitlines() if "testResult" in (event := json.loads(line))]
    by_id = {json.dumps(event["id"]["testResult"], sort_keys=True): event for event in result_events}
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        entries = manifest["test_results"]
        assert len(entries) == 4
        assert {(entry["id"]["label"], entry["id"]["run"]) for entry in entries} == {
            (label, run) for label in targets for run in (1, 2)
        }
        for entry in entries:
            event = by_id[json.dumps(entry["id"], sort_keys=True)]
            assert entry["cached_locally"], "Second invocation must reuse the per-test outputs"
            assert entry["status"] == "PASSED"
            (file,) = [file for file in event["testResult"]["testActionOutput"] if file["name"] == "test.lcov"]
            original = Path(unquote(urlsplit(file["uri"]).path)).read_bytes()
            retained = archive.read(entry["measurement"]["path"])
            assert retained == original
            assert entry["measurement"]["sha256"] == hashlib.sha256(original).hexdigest()
            if backend == "llvm_cov":
                with zipfile.ZipFile(io.BytesIO(retained)) as per_test:
                    metadata = json.loads(per_test.read("meta/meta.json"))
                    assert metadata["test_target"] == entry["id"]["label"]
                    assert per_test.read("profdata/target.profdata")
            else:
                source = b"src/coverable.cpp" if entry["id"]["label"] == targets[0] else b"lib/cross_pkg.cpp"
                assert b"SF:" + source in retained
