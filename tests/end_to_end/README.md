# End-to-end behavior checks

These tests exercise the production coverage tool through a consumer's Bazel
commands and inspect its public reports and CLI results. They provide a behavior
contract for implementation refactoring, without importing reporter internals or
reproducing their algorithms.

Run the Linux end-to-end scenarios:

```sh
bazel test //tests/end_to_end/testcases:all --test_output=errors
```

| Configuration | Execution | Coverage backend |
| --- | --- | --- |
| Clang / Linux | Native | LLVM |
| GCC / Linux | Native | gcov |

The `cpp_semantics_test` target runs both Linux configurations. Compiler/target
selection is kept separate from the coverage backend so additional platforms can
reuse these scenarios. Each configuration collects exactly three
report snapshots: `test_a`, `test_b`, and their combined report. All assertions
reuse those snapshots. Individual tests deliberately leave complementary paths
uncovered; combining their reports must add the measured counts and cover both
outcomes. C++ `CHECK` comments state hand-derived line counts and branch-hit sums
beside the code. Scope checks exclude the linked test driver and retain uncalled
library code. Compiler-specific branch identities are compared within a
configuration, not between compilers.

[`consumer`](consumer) is an independent Bazel module that binds the production module
through a local path override, just as a downstream project would consume it.
Both configurations build the same `cpp_semantics` package, with one set of
sources, arguments and annotations.

LCOV snapshots are retained in each test target's undeclared outputs, named by
compiler/target configuration and test selection. The C++ E2E tests attach
requirement metadata to their JUnit cases.

The CHECK reader and its own unit tests live in [`test_framework`](test_framework).
They test the validation machinery independently of Bazel, compilers and reports:

```sh
bazel test //tests/end_to_end/test_framework:coverage_checks_test
```

These helper tests run with the unit-test CI job, separately from the E2E suite.
