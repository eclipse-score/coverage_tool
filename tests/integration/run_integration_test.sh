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
# End-to-end test of the score_coverage LLVM coverage pipeline, run against
# the consumer/ workspace. Asserts the properties the pipeline
# guarantees:
#   1. Untested in-scope files (C++ AND Rust) appear at exact 0% in the LCOV.
#   2. The effective-coverage gate fails at threshold 100 and passes at a low
#      threshold.
#   3. The justified line raises effective coverage above raw coverage.

set -euo pipefail
cd "$(dirname "$0")/consumer"

# In GitHub Actions GITHUB_STEP_SUMMARY is set for THIS job; unset it so the
# many generate_coverage_html invocations below don't each append to the real
# run page. The dedicated summary test sets its own target file.
unset GITHUB_STEP_SUMMARY || true

echo "=== Running coverage build ==="
bazel coverage --config=llvm_cov //... --build_tests_only

YAML="tools/coverage/coverage_justifications.yaml"

echo "=== Gate must FAIL at threshold 100 (uncovered fixtures exist) ==="
if COVERAGE_THRESHOLD=100 bazel run @score_coverage//:generate_coverage_html -- \
    --yaml "${YAML}" --archive coverage_artifacts; then
  echo "ERROR: coverage gate passed at threshold 100 despite uncovered files" >&2
  exit 1
fi
echo "OK: gate failed as expected"

echo "=== Gate must PASS at a low threshold ==="
COVERAGE_THRESHOLD=10 bazel run @score_coverage//:generate_coverage_html -- \
    --yaml "${YAML}"
echo "OK: gate passed as expected"

echo "=== Without --yaml: HTML still produced, gate applies to RAW coverage ==="
if COVERAGE_THRESHOLD=100 bazel run @score_coverage//:generate_coverage_html; then
  echo "ERROR: raw-coverage gate passed at threshold 100" >&2
  exit 1
fi
COVERAGE_THRESHOLD=10 bazel run @score_coverage//:generate_coverage_html
if [[ ! -f coverage_linux/index.html ]]; then
  echo "ERROR: HTML report missing after no-yaml run" >&2
  exit 1
fi
echo "OK: no-yaml mode works (HTML produced, raw gate enforced)"

# The following sections all run, in order. Each one deletes summary.md
# before its own generate_coverage_html invocation so a stale file from the
# previous section cannot produce a false pass — in particular, the
# failing-gate section must prove the file was RE-created by THAT run.
echo "=== --summary-md must produce a markdown job summary ==="
rm -f summary.md
COVERAGE_THRESHOLD=10 bazel run @score_coverage//:generate_coverage_html -- \
    --yaml "${YAML}" --summary-md summary.md
for marker in "## Coverage summary" "| Lines |" "Raw vs effective" \
              "Coverage by directory" "Files at exact 0% (3)" \
              "| In-scope files without coverage data | 2 |" \
              "In-scope files without coverage data (2)" '- `src/unused_api.h`' '- `src/platform_dep.h`' \
              "Declaration-only headers (3)" "Compiled sources without code of their own (1)" '- `src/empty_unit.cpp`'; do
  if ! grep -qF -- "${marker}" summary.md; then
    echo "ERROR: '${marker}' missing from summary.md" >&2
    exit 1
  fi
done
grep -q "█" summary.md || { echo "ERROR: progress bars missing from summary.md" >&2; exit 1; }
echo "OK: --summary-md works"

echo "=== Summary must still be written when the gate FAILS ==="
rm -f summary.md
if COVERAGE_THRESHOLD=100 bazel run @score_coverage//:generate_coverage_html -- \
    --yaml "${YAML}" --summary-md summary.md; then
  echo "ERROR: gate unexpectedly passed at threshold 100" >&2
  exit 1
fi
[[ -s summary.md ]] || { echo "ERROR: summary.md missing after failing gate" >&2; exit 1; }
echo "OK: summary survives a failing gate"

echo "=== GITHUB_STEP_SUMMARY convenience default (no flag) ==="
rm -f step_summary.md
printf '# existing content\n' > step_summary.md
GITHUB_STEP_SUMMARY="$(pwd)/step_summary.md" COVERAGE_THRESHOLD=10 \
    bazel run @score_coverage//:generate_coverage_html -- --yaml "${YAML}"
grep -qF "# existing content" step_summary.md || { echo "ERROR: append mode overwrote the step summary" >&2; exit 1; }
grep -qF "## Coverage summary" step_summary.md || { echo "ERROR: summary not appended to GITHUB_STEP_SUMMARY" >&2; exit 1; }
rm -f summary.md step_summary.md
echo "OK: GITHUB_STEP_SUMMARY convenience works"

echo "=== --archive-dir must produce an unzipped artifacts tree ==="
COVERAGE_THRESHOLD=10 bazel run @score_coverage//:generate_coverage_html -- \
    --yaml "${YAML}" --archive-dir artifacts_dir
for f in artifacts_dir/coverage_linux/index.html artifacts_dir/coverage_report.dat \
         artifacts_dir/justification_report/summary.txt; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: ${f} missing from --archive-dir output" >&2
    exit 1
  fi
done
# unused_api.h is the finding; coverable.h / uncovered.h hold declarations for
# compiled .cpp files and empty_unit.cpp is a compiled placeholder: categorised.
# platform_dep.h is no-data, not declaration-only: its sources are named per
# variant (platform_host.cpp / platform_target.cpp), not platform_dep.cpp.
EXPECTED_UNMAPPED=$'compiled-without-code\tsrc/empty_unit.cpp\ndeclaration-only\tlib/cross_pkg.h\ndeclaration-only\tsrc/coverable.h\ndeclaration-only\tsrc/uncovered.h\nno-data\tsrc/platform_dep.h\nno-data\tsrc/unused_api.h'
if [[ "$(cat artifacts_dir/unmapped_files.txt)" != "${EXPECTED_UNMAPPED}" ]]; then
  echo "ERROR: unmapped_files.txt unexpected:" >&2
  cat artifacts_dir/unmapped_files.txt >&2
  exit 1
fi
echo "OK: in-scope files without coverage data are listed and categorised in the archive"
rm -rf artifacts_dir
echo "OK: --archive-dir works"

echo "=== Untested files must appear at exact 0% in the LCOV ==="
unzip -p coverage_artifacts.zip artifacts/coverage_report.dat > lcov.dat

check_zero_coverage() {
  local file="$1"
  if ! grep -q "SF:.*${file}" lcov.dat; then
    echo "ERROR: ${file} missing from LCOV (baseline mechanism broken)" >&2
    exit 1
  fi
  # The record for the file must report zero lines hit.
  if ! awk -v f="${file}" '
      $0 ~ "^SF:" && $0 ~ f {rec=1}
      rec && /^LH:/ {print $0; exit ($0 == "LH:0") ? 0 : 1}
      rec && /^end_of_record/ {exit 1}' lcov.dat; then
    echo "ERROR: ${file} is present but not at 0% coverage" >&2
    exit 1
  fi
  echo "OK: ${file} present at 0%"
}

check_zero_coverage "src/uncovered.cpp"
check_zero_coverage "rust/main.rs"

echo "=== LCOV must match the hand-verified ground truth exactly ==="
# Normalise: drop function records, keep one record per file sorted by SF, so
# the comparison is independent of record order and of symbol names.
normalise_lcov() {
  grep -v '^FN' "$1" | awk '
    /^SF:/ { key = $0; rec = "" }
    { rec = rec $0 "\n" }
    /^end_of_record/ { records[key] = rec }
    END { n = asorti(records, keys); for (i = 1; i <= n; i++) printf "%s", records[keys[i]] }'
}
normalise_lcov lcov.dat > actual_normalised.dat
grep -v '^#' ../expected/expected_lcov.dat | normalise_lcov /dev/stdin > expected_normalised.dat
if ! diff -u expected_normalised.dat actual_normalised.dat; then
  echo "ERROR: coverage data differs from expected_lcov.dat (see diff above)" >&2
  exit 1
fi
rm -f actual_normalised.dat expected_normalised.dat
echo "OK: LCOV matches the ground truth"

echo "=== A library tested from a test/ subpackage must be measured (explicit --instrumentation_filter) ==="
# Bazel guesses the filter from the packages of the test targets; //lib is
# outside that guess and would be compiled without instrumentation. The
# config sets the filter explicitly; the golden above holds the numbers.
grep -q "^SF:lib/cross_pkg.cpp$" lcov.dat || { echo "ERROR: lib/cross_pkg.cpp missing: --instrumentation_filter not applied" >&2; exit 1; }
echo "OK: cross-package library measured on the LLVM backend"

echo "=== The scope follows the run's platform: LLVM run (host) reports the host variant only ==="
grep -q "^SF:src/platform_host.cpp$" lcov.dat || { echo "ERROR: host variant platform_host.cpp missing from the LLVM report" >&2; exit 1; }
if grep -q "platform_target.cpp" lcov.dat; then echo "ERROR: target variant leaked into the host (LLVM) report" >&2; exit 1; fi
grep -q "^SF:src/host_root.cpp$" lcov.dat || { echo "ERROR: host root (select in the scope deps) missing from the LLVM report" >&2; exit 1; }
if grep -q "target_root.cpp" lcov.dat; then echo "ERROR: target root leaked into the host (LLVM) report" >&2; exit 1; fi
echo "OK: platform-selected library reported as the host variant on the LLVM run"

echo "=== Every index link must point at an existing page; no machine or config paths ==="
rm -rf link_check && mkdir link_check
unzip -q coverage_artifacts.zip -d link_check
HTML_DIR="link_check/artifacts/coverage_linux"
[[ -f "${HTML_DIR}/index.html" ]] || { echo "ERROR: ${HTML_DIR}/index.html missing" >&2; exit 1; }
LINKS="$(grep -oE "href='coverage/[^']+\.html'" "${HTML_DIR}/index.html" | sed -E "s/^href='//; s/'$//")"
[[ -n "${LINKS}" ]] || { echo "ERROR: no source links in index.html" >&2; exit 1; }
while IFS= read -r link; do
  if [[ ! -f "${HTML_DIR}/${link}" ]]; then
    echo "ERROR: index.html links to ${link}, which was not generated" >&2
    exit 1
  fi
  case "${link}" in
    coverage/bazel-out/*|coverage/home/*|coverage/tmp/*|*/_virtual_includes/*)
      echo "ERROR: index.html link is not a canonical workspace path: ${link}" >&2
      exit 1 ;;
  esac
  # The page's stylesheet link must resolve from the page's location.
  page_dir="$(dirname "${HTML_DIR}/${link}")"
  css="$(grep -oE "href='(\.\./)*style\.css'" "${HTML_DIR}/${link}" | head -1 | sed -E "s/^href='//; s/'$//")"
  if [[ -z "${css}" || ! -f "${page_dir}/${css}" ]]; then
    echo "ERROR: ${link}: stylesheet link '${css}' does not resolve" >&2
    exit 1
  fi
done <<< "${LINKS}"
for page in "coverage/src/vendored/include/vendored/inline_math.h.html" \
            "coverage/external/itest_external+/include/vext/vext.h.html"; do
  grep -qF "href='${page}'" "${HTML_DIR}/index.html" || { echo "ERROR: ${page} not linked from index.html" >&2; exit 1; }
done
if grep -q "itest_external+/extlib" "${HTML_DIR}/index.html"; then
  echo "ERROR: forwarded third-party library leaked into the HTML report" >&2
  exit 1
fi
if grep -q "extlib" lcov.dat; then
  echo "ERROR: forwarded third-party library leaked into the LCOV" >&2
  exit 1
fi
rm -rf link_check
echo "OK: $(echo "${LINKS}" | wc -l) index links resolve, canonical paths only, third-party code excluded"

echo "=== A header compiled only through a test-only twin target must be attributed to the declared file ==="
# Without the fallback the data sits under _virtual_includes/vendored_math_internal/
# (a target outside the scope), gets excluded, and the header is listed as no-data.
grep -q "^SF:src/vendored/include/vendored/inline_math.h$" lcov.dat || { echo "ERROR: inline_math.h not attributed to its declared path" >&2; exit 1; }
if grep -q "vendored_math_internal" lcov.dat artifacts_dir/unmapped_files.txt 2>/dev/null; then
  echo "ERROR: the test-only twin's virtual path leaked into the report" >&2; exit 1
fi
echo "OK"

echo "=== A header nothing includes must be reported as unmapped, not invented in the LCOV ==="
if grep -q "unused_api" lcov.dat; then
  echo "ERROR: src/unused_api.h has no compiled code and must not have an LCOV record" >&2
  exit 1
fi
echo "OK"

echo "=== Covered files must be present with hits ==="
grep -q "SF:.*src/coverable.cpp" lcov.dat || { echo "ERROR: coverable.cpp missing" >&2; exit 1; }
grep -q "SF:.*rust/lib.rs" lcov.dat || { echo "ERROR: lib.rs missing" >&2; exit 1; }
echo "OK"

echo "=== Justified line must raise effective coverage above raw ==="
SUMMARY="$(unzip -p coverage_artifacts.zip artifacts/justification_report/summary.txt)"
echo "${SUMMARY}"
JUSTIFIED="$(echo "${SUMMARY}" | grep -oP 'Justified lines:\s+\K[0-9]+')"
if [[ "${JUSTIFIED}" -lt 1 ]]; then
  echo "ERROR: expected at least one justified line, got ${JUSTIFIED}" >&2
  exit 1
fi
RAW="$(echo "${SUMMARY}" | grep -oP 'Raw line coverage:\s+\K[0-9.]+')"
EFFECTIVE="$(echo "${SUMMARY}" | grep -oP 'Effective line coverage:\s+\K[0-9.]+')"
if ! awk "BEGIN {exit (${EFFECTIVE} > ${RAW}) ? 0 : 1}"; then
  echo "ERROR: effective coverage ${EFFECTIVE}% not above raw ${RAW}%" >&2
  exit 1
fi
echo "OK: effective ${EFFECTIVE}% > raw ${RAW}%"

echo "=== Fault injection: a broken report must yield NO verdict (exit 2), never a pass ==="
REPORT="bazel-out/_coverage/_coverage_report.dat"
cp "${REPORT}" report.backup
chmod u+w "${REPORT}"
printf 'this is not a zip archive' > "${REPORT}"
set +e
COVERAGE_THRESHOLD=0 bazel run @score_coverage//:generate_coverage_html > /dev/null 2>&1
rc=$?
set -e
cp report.backup "${REPORT}"
rm -f report.backup
if [[ "${rc}" -ne 2 ]]; then
  echo "ERROR: corrupt report gave exit code ${rc}, expected 2" >&2
  exit 1
fi
echo "OK: corrupt report is rejected with exit 2"

echo "=== Fault injection: a non-numeric threshold must be rejected (exit 2) ==="
set +e
COVERAGE_THRESHOLD=lenient bazel run @score_coverage//:generate_coverage_html > /dev/null 2>&1
rc=$?
set -e
if [[ "${rc}" -ne 2 ]]; then
  echo "ERROR: bad threshold gave exit code ${rc}, expected 2" >&2
  exit 1
fi
echo "OK: invalid threshold is rejected with exit 2"

echo "=== Fault injection: an unknown justification id must not count as covered ==="
sed -i 's/itest-positive-branch/itest-typo-branch/' src/coverable.cpp
set +e
COVERAGE_THRESHOLD=10 bazel run @score_coverage//:generate_coverage_html -- --yaml "${YAML}" --archive-dir typo_dir > typo.log 2>&1
rc=$?
set -e
sed -i 's/itest-typo-branch/itest-positive-branch/' src/coverable.cpp
if [[ "${rc}" -ne 0 ]]; then
  cat typo.log
  echo "ERROR: run with an unknown marker id failed unexpectedly (${rc})" >&2
  exit 1
fi
grep -q "references unknown ID 'itest-typo-branch'" typo.log || { echo "ERROR: unknown marker id was not reported" >&2; exit 1; }
TYPO_EFFECTIVE="$(grep -oP 'Effective line coverage:\s+\K[0-9.]+' typo_dir/justification_report/summary.txt)"
TYPO_RAW="$(grep -oP 'Raw line coverage:\s+\K[0-9.]+' typo_dir/justification_report/summary.txt)"
if [[ "${TYPO_EFFECTIVE}" != "${TYPO_RAW}" ]]; then
  echo "ERROR: unknown marker id still raised effective (${TYPO_EFFECTIVE}) above raw (${TYPO_RAW})" >&2
  exit 1
fi
rm -rf typo_dir typo.log
echo "OK: unknown justification id is reported and does not count"

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
