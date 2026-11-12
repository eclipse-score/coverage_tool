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

"""Observe Bazel's per-test hook and collect gcovr JSON alongside normal LCOV."""

import argparse
import gzip
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from gcovr.__main__ import main as gcovr_main
from python.runfiles import runfiles


def main() -> None:
    """Keep normal LCOV output and publish a separate per-test JSON artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage_dir", type=Path, required=True)
    parser.add_argument("--output_file", type=Path, required=True)
    args, _ = parser.parse_known_args()
    root = Path(os.environ["ROOT"])
    evidence = Path(os.environ["TEST_UNDECLARED_OUTPUTS_DIR"]) / "gcovr-experiment"
    evidence.mkdir(parents=True, exist_ok=True)
    gcov = Path(os.environ["COVERAGE_GCOV_PATH"])
    if not gcov.is_absolute():
        gcov = root / gcov
    gcov = gcov.resolve()
    # This toolchain's gcov_wrapper is a shell script without a shebang.
    # Bazel's shell collector executes it through Bash's ENOEXEC fallback;
    # Python and gcovr need that interpreter explicitly. Real gcov binaries
    # and scripts with a shebang remain directly executable.
    with gcov.open("rb") as stream:
        prefix = stream.read(4)
    gcov_command = [str(gcov)] if prefix.startswith((b"#!", b"\x7fELF")) else ["bash", str(gcov)]

    # Record only relevant environment fields, never credentials or the full
    # test environment. Inventory is captured before either merger runs.
    inventory = {
        "test_target": os.environ.get("TEST_TARGET"),
        "gcov_version": subprocess.check_output([*gcov_command, "--version"], text=True),
        "gcov": str(gcov),
        "root": str(root),
        "coverage_dir": str(args.coverage_dir),
        "files": [
            {"path": str(p.relative_to(args.coverage_dir)), "bytes": p.stat().st_size}
            for p in sorted(args.coverage_dir.rglob("*"))
            if p.is_file()
        ],
        "gcov_json_versions": sorted(
            {
                json.loads(gzip.decompress(p.read_bytes()))["format_version"]
                for p in args.coverage_dir.rglob("*.gcov.json.gz")
            }
        ),
    }
    (evidence / "hook.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")

    # Resolve the same executable as @bazel_tools//tools/test:lcov_merger.
    # That alias points into bazel_tools' remote_coverage_tools repository.
    resolver = runfiles.Create()
    if resolver is None:
        raise RuntimeError("The experimental collector requires Bazel runfiles")
    merger = resolver.Rlocation("remote_coverage_tools/Main", source_repo="bazel_tools")
    if merger is None:
        raise RuntimeError("Bazel's LCOV merger is missing from collector runfiles")
    subprocess.run([merger, *sys.argv[1:]], check=True)
    shutil.copyfile(args.output_file, evidence / "bazel.lcov")

    # Explicit fixture-only source staging: compilation inputs are not test
    # inputs by default. Production integration must provide matching sources
    # too; silently ignoring missing source errors would invalidate the probe.
    fixture = Path("experiments/gcovr_per_test")
    sources = Path(os.environ["TEST_SRCDIR"]) / os.environ["TEST_WORKSPACE"] / fixture
    shutil.copytree(sources, root / fixture, dirs_exist_ok=True)

    # GCC 12's JSON v1 is not a gcovr input. Run the matching gcov again over
    # retained counters/notes; gcovr selects its text parser automatically.
    sys.argv = [
        "gcovr",
        "--verbose",
        "--root",
        str(root),
        "--filter",
        os.environ.get("EXPERIMENT_SOURCE_FILTER", "experiments/gcovr_per_test/"),
        "--gcov-executable",
        shlex.join(gcov_command),
        "--gcov-object-directory",
        str(root),
        "--json",
        str(evidence / "measurement.json"),
        str(args.coverage_dir),
    ]
    raise SystemExit(gcovr_main())


if __name__ == "__main__":
    main()
