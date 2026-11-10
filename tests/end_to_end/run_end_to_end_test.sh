#!/usr/bin/env bash
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
# Remaining end-to-end checks for LLVM error handling and the gcov pipeline.

set -euo pipefail
cd "$(dirname "$0")/consumer"

# In GitHub Actions GITHUB_STEP_SUMMARY is set for THIS job; unset it so the
# many generate_coverage_html invocations below don't each append to the real
# run page. The dedicated summary test sets its own target file.
unset GITHUB_STEP_SUMMARY || true

echo "=== Running coverage build ==="
bazel coverage --config=llvm_cov //... --build_tests_only

YAML="tools/coverage/coverage_justifications.yaml"

echo "=== Generate coverage archive for CI ==="
COVERAGE_THRESHOLD=10 bazel run @score_coverage//:generate_coverage_html -- \
    --yaml "${YAML}" --archive coverage_artifacts

# Normalise: drop function records, keep one record per file sorted by SF, so
# the comparison is independent of record order and of symbol names.
normalise_lcov() {
  grep -v '^FN' "$1" | awk '
    /^SF:/ { key = $0; rec = "" }
    { rec = rec $0 "\n" }
    /^end_of_record/ { records[key] = rec }
    END { n = asorti(records, keys); for (i = 1; i <= n; i++) printf "%s", records[keys[i]] }'
}

# ---------------------------------------------------------------------------
# gcov backend: GCC toolchain, Bazel's own per-test collector, score_coverage's
# gcov reporter. The same path a QNX (QCC) on-target run takes; only the QEMU
# transport of score_qnx_unit_tests differs.
# ---------------------------------------------------------------------------
echo "=== gcov backend: coverage build with the GCC toolchain ==="
bazel coverage --config=gcov //src/... //lib/... --build_tests_only

echo "=== gcov backend: gate, HTML, archive ==="
rm -rf gcov_artifacts_dir
if COVERAGE_THRESHOLD=100 bazel run @score_coverage//:generate_coverage_html -- \
    --yaml "${YAML}" --archive-dir gcov_artifacts_dir --summary-md gcov_summary.md coverage_gcov > gcov_run.log 2>&1; then
  cat gcov_run.log
  echo "ERROR: gcov gate passed at threshold 100 despite uncovered files" >&2
  exit 1
fi
grep -q "Effective coverage" gcov_run.log || { cat gcov_run.log; echo "ERROR: gcov run did not reach the gate" >&2; exit 1; }
COVERAGE_THRESHOLD=10 bazel run @score_coverage//:generate_coverage_html -- \
    --yaml "${YAML}" --archive-dir gcov_artifacts_dir --summary-md gcov_summary.md coverage_gcov
echo "OK: gcov gate fails at 100 and passes at 10"

echo "=== gcov backend: LCOV must match the hand-verified ground truth ==="
normalise_lcov gcov_artifacts_dir/coverage_report.dat > actual_gcov.dat
grep -v '^#' ../expected/expected_lcov_gcov.dat | normalise_lcov /dev/stdin > expected_gcov.dat
if ! diff -u expected_gcov.dat actual_gcov.dat; then
  echo "ERROR: gcov coverage data differs from expected_lcov_gcov.dat (see diff above)" >&2
  exit 1
fi
rm -f actual_gcov.dat expected_gcov.dat
echo "OK: gcov LCOV matches the ground truth"

echo "=== gcov backend: every index link opens; justification applied; categories ==="
GHTML="gcov_artifacts_dir/coverage_gcov"
[[ -f "${GHTML}/index.html" ]] || { echo "ERROR: gcovr index.html missing" >&2; exit 1; }
GLINKS="$(grep -oE 'href="index\.[^"]+\.html"' "${GHTML}/index.html" | sed -E 's/^href="//; s/"$//' | sort -u)"
[[ -n "${GLINKS}" ]] || { echo "ERROR: no per-file links in the gcovr index" >&2; exit 1; }
while IFS= read -r link; do
  [[ -f "${GHTML}/${link}" ]] || { echo "ERROR: gcovr index links to ${link}, which does not exist" >&2; exit 1; }
done <<< "${GLINKS}"
for page in coverable.cpp uncovered.cpp inline_math.h cross_pkg.cpp platform_target.cpp target_root.cpp; do
  ls "${GHTML}"/index."${page}".*.html > /dev/null 2>&1 || { echo "ERROR: no gcovr page for ${page}" >&2; exit 1; }
done
G_RAW="$(grep -oP 'Raw line coverage:\s+\K[0-9.]+' gcov_artifacts_dir/justification_report/summary.txt)"
G_EFF="$(grep -oP 'Effective line coverage:\s+\K[0-9.]+' gcov_artifacts_dir/justification_report/summary.txt)"
if ! awk "BEGIN {exit (${G_EFF} > ${G_RAW}) ? 0 : 1}"; then
  echo "ERROR: gcov effective coverage ${G_EFF}% not above raw ${G_RAW}% (justification not applied on gcovr HTML)" >&2
  exit 1
fi
EXPECTED_GCOV_UNMAPPED=$'compiled-without-code\tsrc/empty_unit.cpp\ndeclaration-only\tlib/cross_pkg.h\ndeclaration-only\tsrc/coverable.h\ndeclaration-only\tsrc/uncovered.h\nno-data\tsrc/platform_dep.h\nno-data\tsrc/unused_api.h\nnot-instrumented\trust/lib.rs\nnot-instrumented\trust/main.rs'
if [[ "$(cat gcov_artifacts_dir/unmapped_files.txt)" != "${EXPECTED_GCOV_UNMAPPED}" ]]; then
  echo "ERROR: gcov unmapped_files.txt unexpected:" >&2
  cat gcov_artifacts_dir/unmapped_files.txt >&2
  exit 1
fi
grep -qF "Not instrumentable by this backend (2)" gcov_summary.md || { echo "ERROR: not-instrumented section missing from the gcov summary" >&2; exit 1; }
echo "=== The scope follows the run's platform: gcov run (//platforms:gcov_target) reports the target variant only ==="
# coverage_scope_gcov carries platform = //platforms:gcov_target; without it
# the scope would be analysed for the host (exec configuration) and list
# platform_host.cpp at 0 % instead (coverage_tool#23).
grep -q "^SF:src/platform_target.cpp$" gcov_artifacts_dir/coverage_report.dat || { echo "ERROR: target variant platform_target.cpp missing from the gcov report: scope not evaluated for the run's platform" >&2; exit 1; }
if grep -q "platform_host.cpp" gcov_artifacts_dir/coverage_report.dat; then echo "ERROR: host variant leaked into the gcov report: scope evaluated for the host" >&2; exit 1; fi
# The select() in the scope's deps resolved for the gcov platform: the target
# root is in, the (incompatible) host root out, and the tests were executed.
grep -q "^SF:src/target_root.cpp$" gcov_artifacts_dir/coverage_report.dat || { echo "ERROR: target root (select in the scope deps) missing from the gcov report" >&2; exit 1; }
if grep -q "host_root.cpp" gcov_artifacts_dir/coverage_report.dat; then echo "ERROR: host root leaked into the gcov report" >&2; exit 1; fi
echo "OK: platform-selected library reported as the target variant on the gcov run"

rm -rf gcov_artifacts_dir gcov_summary.md gcov_run.log coverage_gcov
echo "OK: gcov HTML complete (${GLINKS//$'\n'/, }), effective ${G_EFF}% > raw ${G_RAW}%, categories as expected"

echo "=== gcov backend: without the explicit filter the reporter must point at --instrumentation_filter ==="
# Bazel's guessed filter for these targets is ^//lib/test[/:],^//src[/:]; pass
# it explicitly to reproduce a consumer config that forgot the flag. Bazel's
# collector then drops lib/cross_pkg.cpp's counters; the file falls back to
# the 0 % baseline and the reporter must name the cause.
bazel coverage --config=gcov '--instrumentation_filter=^//lib/test[/:],^//src[/:]' //src/... //lib/... --build_tests_only > gcov_narrow.log 2>&1 || { cat gcov_narrow.log; exit 1; }
grep -q "WARNING: 1 in-scope files have no test data although their directory is tested from a test/ or tests/ subdirectory" gcov_narrow.log \
  || { cat gcov_narrow.log; echo "ERROR: the reporter did not warn about the narrow --instrumentation_filter" >&2; exit 1; }
grep -q -- "--instrumentation_filter=\^//<root package>\[/:\]" gcov_narrow.log || { echo "ERROR: the warning does not name the flag to set" >&2; exit 1; }
unzip -p bazel-out/_coverage/_coverage_report.dat lcov_report/lcov.dat | awk '/^SF:lib\/cross_pkg.cpp$/{p=1} p&&/^LH:/{print; exit}' | grep -q "^LH:0$" \
  || { echo "ERROR: expected lib/cross_pkg.cpp at 0 % under the narrow filter" >&2; exit 1; }
rm -f gcov_narrow.log
echo "OK: narrow --instrumentation_filter is detected and reported"

echo ""
echo "=== All integration checks passed ==="
