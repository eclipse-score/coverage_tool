# Per-test gcovr JSON experiment

This opt-in example investigates the backend-data choice in
[#61](https://github.com/eclipse-score/coverage_tool/issues/61). It leaves the
production collectors and combined reporters unchanged.

**Status: the Linux GCC 12 control experiment works. QNX is not validated.**
No QNX SDP/QCC installation, QEMU executable or running QNX container was
available in the investigation environment. The QNX part of #61 remains open.

The `Per-test gcovr QNX experiment` workflow runs on pushes to the upstream
`experiment/gcovr-per-test` branch. It checks for `SCORE_BOT_QNX_PKG_PAT` and
`SCORE_QNX_LICENSE`, installs QEMU, and runs the QNX variant. The package token
downloads the pinned private SDP asset; QNX website credentials are not needed.
The license secret must be made available to coverage_tool separately if missing.

## Reproduce the control experiment

From the coverage_tool checkout, choose a new output directory:

```sh
python3 experiments/gcovr_per_test/run.py --output /tmp/gcovr-per-test-evidence
```

With QEMU, the license at `/opt/score_qnx/license/licenses`, and `GH_TOKEN`
providing read access to the private SDP package, use `--qnx`:

```sh
python3 experiments/gcovr_per_test/run.py --qnx --output /tmp/gcovr-qnx-evidence
```

This creates an isolated QNX consumer under the output directory, using the
same fixture sources and the existing S-CORE QNX runner. The ordinary Linux
consumer does not acquire QNX dependencies. CI uploads only experiment evidence,
excluding that generated workspace, Bazel directories, the SDP and the license.

The script uses the existing consumer workspace and its pinned Linux GCC
toolchain. Bazel supplies the compiler, gcov and gcovr dependencies. The two
fixture targets are tagged `manual`, so ordinary consumer coverage runs exclude
them.

The script runs two Bazel test targets through an experimental
`--coverage_output_generator`, then creates three selections: the positive
test, the negative test, and both. All selection processing uses saved files;
there is no further test execution or coverage collection.

The output directory contains:

- `commands.json` and logs: exact commands, working directories and diagnostics.
- `<test>/hook.json`: the test label, actual gcov version and the files available
  at the hook before the experimental processing.
- `<test>/measurement.json`: gcovr's per-test measurement.
- `<test>/bazel.lcov`: the result from Bazel's ordinary per-test merger.
- `<selection>/merged.json` and `gcovr.lcov`: gcovr's selected results.
- `<selection>/bazel.lcov`: the same selection merged by Bazel's LCOV merger.
- `comparison.json`: covered/total line, branch and function counts per file.

The script rejects differences in those counts. It normalizes the absolute
source paths written by gcovr's LCOV exporter to the workspace-relative paths
written by Bazel. It does not establish arbitrary cross-build compatibility or
equivalence of every branch identity.

## Observed results

With Bazel 8.6.0, the S-CORE Linux GCC/gcov 12.2.0 toolchain and gcovr 8.6:

| Selection | Subject lines | Subject branches | Subject functions |
| --- | --- | --- | --- |
| Positive test | 3/6 | 1/2 | 1/2 |
| Negative test | 3/6 | 1/2 | 1/2 |
| Both | 4/6 | 2/2 | 1/2 |

These counts match Bazel's LCOV path for all three selections, including the
test source. The never-called function remains visible at zero hits.

At the per-test hook, Bazel has already run `collect_cc_coverage.sh`. The hook
still has `.gcda` counters and matching `.gcno` notes, alongside compressed
gcov JSON with `format_version: "1"`. gcovr 8.6 does not read that JSON format;
it invokes gcov again over the counters and notes, using its text parser.
This is consistent with the [gcovr 8.6 parser documentation](https://gcovr.com/en/8.6/guide/gcov_parser.html).

The generated gcovr JSON has format `0.14`. In this fixture it retains
line-to-function associations, function block coverage, branch fallthrough and
throw flags, source block IDs, and source-line checksums. Bazel's existing LCOV
output does not contain all of these fields. This is evidence of additional
detail in this example, not evidence that every native gcov detail survives.
The fixture does not demonstrate condition coverage or MC/DC.

There is also an observed merge limitation: `classify(int)` reports
`blocks_percent: 75.0` in each test and still reports `75.0` after merging both,
even though the merged branch coverage includes both outcomes. gcovr combines
that percentage using the maximum input value, not a union of covered blocks.
Do not treat every extra JSON field as an accurately recomputable aggregate.

## Integration constraints exposed by the probe

**Source files must be available.** Bazel makes counters and notes available to
the hook, but compilation sources are not automatically test inputs. Without
sources, gcovr's GCC-12 text path failed with `Cannot open source file`. The
fixture explicitly declares both sources as test data, and the collector stages
them at their compilation-relative paths. That staging is deliberately specific
to the fixture. Production integration needs its own source-input contract.

**The gcov wrapper assumes an execution-root working directory.** The pinned
S-CORE Linux toolchain uses a shell wrapper without a shebang and with an
execution-root-relative compiler path. The probe invokes it with Bash and gives
gcovr the execution root as its object directory. A different toolchain's
wrapper must be checked independently.

**gcov runs twice in this arrangement.** Bazel performs its collection before
calling the hook. The probe then runs gcovr and delegates normal LCOV generation
to Bazel. This confirms feasibility at the existing hook, but does not measure
or optimize collection overhead.

**This example's extra JSON is a test artifact.** It is written under
`TEST_UNDECLARED_OUTPUTS_DIR`, not delivered to the production combined reporter.
The script copies it out before replay. It does not solve the measurement
packaging, shard/run identity or caching requirements of #54.

## QNX validation still needed

Run the same two source-level cases using the supported QCC/QNX gcov pair and
the existing QNX test runner. Record the actual SDP, QCC, gcov and runner
versions. Check the counter paths returned by the runner against the coverage
manifest and inspect the hook inventory; Linux success does not establish that
the QNX counter transport produces the same layout.

The inspected cached S-CORE QNX runner extracts returned counters into
`COVERAGE_DIR` as well as test artifacts. That is a promising integration point,
but source inspection is not an executed QNX result. The probe's source staging
and Linux configuration must not be presented as a ready-made QNX setup.

## Recommendation

Keep gcovr JSON as the candidate native gcov contribution format. The Linux
control demonstrates collection through the existing hook and selected merging
without rerunning tests. Do not choose a production gcov packaging contract or
change #60's backend design on this result alone: validate the QNX path and
resolve source availability first.

If exact recomputation of block coverage or other details lost by the text/JSON
path is required, gcovr JSON alone is insufficient evidence of preservation.
Retaining raw counters and matching notes may still be necessary; this probe
does not implement or validate their later native merging.

The shared selection/backend-dispatch structure in #60 remains compatible with
this candidate. If QNX confirms it, the smallest production integration would
prepare gcovr JSON per test and let the gcov backend merge selected JSON files.
Retaining test identity, artifact transport, baseline handling and later replay
inputs remain separate responsibilities.
