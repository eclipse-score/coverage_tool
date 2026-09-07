<!-- ----------------------------------------------------------------------------
  Copyright (c) 2026 Contributors to the Eclipse Foundation

  See the NOTICE file(s) distributed with this work for additional
  information regarding copyright ownership.

  This program and the accompanying materials are made available under the
  terms of the Apache License Version 2.0 which is available at
  https://www.apache.org/licenses/LICENSE-2.0

  SPDX-License-Identifier: Apache-2.0
----------------------------------------------------------------------------- -->

# coverage_tool — Bazel module `score_coverage`

LLVM source-based code coverage pipeline for Eclipse S-CORE: one
`bazel coverage` run gives one line and branch coverage report for C++ and
Rust, untested in-scope files at exact 0 %, reviewed justifications with an
effective-coverage metric, and a CI threshold gate.

The tool is developed as a software tool under the S-CORE tool-management
process (ISO 26262-8 clause 11). It is the successor of
`@score_tooling//coverage`.

## Documentation

The documentation is docs-as-code under [`docs/`](docs/) and published at
<https://eclipse-score.github.io/coverage_tool>:

- **User manual** — adoption guide (six steps), command reference,
  [constraints of use](docs/manual/constraints.rst) and
  [known problems](docs/manual/known_problems.rst).
- **Requirements** — use cases, potential errors (HazOp style) and the tool
  requirements the tests verify.
- **Architecture** — the two-phase pipeline and the module/consumer split.
- **Verification report** — test inventory, structural coverage of the tool,
  static analysis, end-to-end validation, deviations.

Build it locally with `bazel run //docs:docs` (output in `docs/_build/`) or
`bazel run //docs:live_preview`.

## Quick start

```bash
bazel coverage --config=llvm_cov //... --build_tests_only
bazel run @score_coverage//:generate_coverage_html -- \
    --yaml tools/coverage/coverage_justifications.yaml --archive-dir coverage_artifact
```

Exit codes: `0` gate passed, `1` gate failed, `2` no verdict possible.

## Repository layout

- `defs.bzl`, `BUILD` — the public API (`score_coverage_scope`,
  `score_coverage_reporter`, `//:merger`, `//:generate_coverage_html`,
  `//:enable_llvm_coverage_for_death_tests`). The root package loads only
  runtime dependencies so it stays loadable for consumers.
- `score_coverage/` — implementation (Python report tooling, Starlark rules) and
  unit tests, including Starlark analysis tests.
- `integration_tests/` — a self-contained consumer workspace (C++ + Rust)
  exercised end to end by `run_integration_test.sh` against a hand-derived
  ground truth (`expected_lcov.dat`); also the reference for the adoption guide.
- `tools/` — repository hygiene (copyright, format, lint aspects) and the
  self-coverage gate.
- `docs/` — the docs-as-code tree.

## Development

```bash
bazel test //score_coverage/... //tools/...          # unit + analysis tests
bazel build --config=lint //score_coverage/... //tools/...   # ruff, pylint, ty
bazel coverage --combined_report=lcov //score_coverage/tests:all
bazel run //tools:self_coverage_gate -- --min-lines 95 --min-branches 87
integration_tests/run_integration_test.sh            # end-to-end (downloads LLVM + Ferrocene)
bazel run //tools:format.fix && bazel run //tools:copyright.check
```
