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

"""Collect two Bazel tests, then compare offline gcovr selections with Bazel LCOV."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def metrics(text: str, root: Path) -> dict[str, dict[str, tuple[int, int]]]:
    """Return covered/total counts per source, independent of function mangling."""
    result = {}
    current = None
    names = {
        "LH": ("lines", 0),
        "LF": ("lines", 1),
        "BRH": ("branches", 0),
        "BRF": ("branches", 1),
        "FNH": ("functions", 0),
        "FNF": ("functions", 1),
    }
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key == "SF":
            # gcovr's LCOV writer uses absolute paths, Bazel uses workspace
            # paths. Normalize only that representation difference.
            if Path(value).is_absolute():
                value = str(Path(value).relative_to(root))
            current = {name: [0, 0] for name in ("lines", "branches", "functions")}
            result[value] = current
        elif key in names and current is not None:
            name, index = names[key]
            current[name][index] = int(value)
    return {file: {name: tuple(counts) for name, counts in data.items()} for file, data in result.items()}


def main() -> None:
    """Record collection and replay evidence in a fresh output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qnx", action="store_true", help="Use the isolated QNX/QEMU consumer")
    args = parser.parse_args()
    output = args.output.resolve()
    # Test artifacts can be read-only. Require a fresh evidence directory
    # rather than overwriting results from another run.
    output.mkdir(parents=True)
    repository = Path(__file__).resolve().parents[2]
    consumer = repository / "tests/end_to_end/consumer"
    package = "experiments/gcovr_per_test"
    config = "gcov"
    if args.qnx:
        # Keep QNX dependencies and credentials out of the normal consumer.
        # Both consumers compile the exact same fixture at the same source paths.
        consumer = output / "qnx-consumer"
        fixture = consumer / package
        shutil.copytree(repository / "tests/end_to_end/consumer" / package, fixture)
        template = Path(__file__).parent / "qnx"
        module = (template / "MODULE.bazel.in").read_text(encoding="utf-8")
        module = module.replace("COVERAGE_TOOL_PATH", json.dumps(str(repository)))
        (consumer / "MODULE.bazel").write_text(module, encoding="utf-8")
        shutil.copyfile(template / "bazelrc", consumer / ".bazelrc")
        shutil.copyfile(repository / ".bazelversion", consumer / ".bazelversion")
        config = "qnx"
    tests = ["positive_test", "negative_test"]
    commands = []

    def run(command: list[str], cwd: Path, log: str) -> None:
        commands.append({"cwd": str(cwd), "argv": command})
        (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
        with (output / log).open("w", encoding="utf-8") as stream:
            subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, check=True)

    try:
        run(
            [
                "bazel",
                "coverage",
                f"--config={config}",
                "--combined_report=none",
                "--coverage_output_generator=@score_coverage//experiments/gcovr_per_test:collector",
                "--nozip_undeclared_test_outputs",
                *[f"//{package}:{test}" for test in tests],
            ],
            consumer,
            "collection.log",
        )
    finally:
        # A failed collector may already have a useful hook inventory.
        for test in tests:
            evidence = consumer / "bazel-testlogs" / package / test / "test.outputs/gcovr-experiment"
            if evidence.is_dir():
                shutil.copytree(evidence, output / test)

    if args.qnx:
        external = consumer / f"bazel-{consumer.name}" / "external"
        sdp = next(external.glob("*score_qcc_x86_64_toolchain_pkg"))
        host = sdp / "host/linux/x86_64"
        version = subprocess.run(
            [str(host / "usr/bin/qcc"), "-V"],
            env={**os.environ, "QNX_HOST": str(host), "QNX_TARGET": str(sdp / "target/qnx")},
            capture_output=True,
            text=True,
            check=False,
        )
        (output / "qcc-version.json").write_text(
            json.dumps(
                {"returncode": version.returncode, "stdout": version.stdout, "stderr": version.stderr}, indent=2
            ),
            encoding="utf-8",
        )

    # From here on only saved JSON and LCOV are read. There is no coverage or
    # test invocation: these selections do not rebuild or re-execute the tests.
    comparison = {}
    for selection, selected in [("positive", tests[:1]), ("negative", tests[1:]), ("both", tests)]:
        destination = output / selection
        destination.mkdir(exist_ok=True)
        lcov_inputs = destination / "lcov-inputs"
        lcov_inputs.mkdir(exist_ok=True)
        for test in selected:
            shutil.copyfile(output / test / "bazel.lcov", lcov_inputs / f"{test}.dat")
        run(
            [
                "bazel",
                "run",
                "@bazel_tools//tools/test:lcov_merger",
                "--",
                f"--coverage_dir={lcov_inputs}",
                f"--output_file={destination / 'bazel.lcov'}",
            ],
            repository,
            f"{selection}-bazel.log",
        )
        json_args = [
            arg for test in selected for arg in ["--json-add-tracefile", str(output / test / "measurement.json")]
        ]
        run(
            [
                "bazel",
                "run",
                "//experiments/gcovr_per_test:gcovr",
                "--",
                "--root",
                str(consumer),
                *json_args,
                "--json",
                str(destination / "merged.json"),
                "--lcov",
                str(destination / "gcovr.lcov"),
            ],
            repository,
            f"{selection}-gcovr.log",
        )
        bazel_metrics = metrics((destination / "bazel.lcov").read_text(encoding="utf-8"), consumer)
        gcovr_metrics = metrics((destination / "gcovr.lcov").read_text(encoding="utf-8"), consumer)
        expected_sources = {f"{package}/subject.cpp", f"{package}/test.cpp"}
        if set(bazel_metrics) != expected_sources or set(gcovr_metrics) != expected_sources:
            raise SystemExit(f"Selection {selection} is missing fixture sources; inspect {destination}")
        comparison[selection] = {
            "bazel": bazel_metrics,
            "gcovr": gcovr_metrics,
            "equal": bazel_metrics == gcovr_metrics,
        }
    (output / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    if not all(item["equal"] for item in comparison.values()):
        raise SystemExit(f"Coverage counts differ; inspect {output / 'comparison.json'}")
    print(f"All three selections match Bazel's line, branch and function totals. Evidence: {output}")


if __name__ == "__main__":
    main()
