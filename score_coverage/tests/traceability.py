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
"""Link test classes to the tool requirements they verify.

``@verifies(...)`` applies score_tooling's ``add_test_properties`` to every
``test_*`` method of a ``unittest.TestCase`` class. Under ``score_py_pytest`` the
properties (``PartiallyVerifies`` / ``FullyVerifies``, ``TestType``,
``DerivationTechnique``) end up in the JUnit XML that docs-as-code turns into
``testcase`` needs and ``testlink`` back-references on the requirements
(``gd_req__verification_link_tests_python``).

Outside Bazel (plain ``python -m unittest``) the plugin is absent and the
decorator is a no-op, so the tests stay runnable from an IDE.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

try:
    from attribute_plugin import add_test_properties  # type: ignore[import-not-found]  # ty: ignore[unresolved-import]
except ImportError:  # pragma: no cover - only outside of score_py_pytest

    def add_test_properties(**_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """No-op replacement when the pytest plugin is not available."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func

        return decorator


TestType = Literal["fault-injection", "interface-test", "requirements-based", "resource-usage"]
Derivation = Literal[
    "requirements-analysis",
    "design-analysis",
    "boundary-values",
    "equivalence-classes",
    "fuzz-testing",
    "error-guessing",
    "explorative-testing",
]


def _description_from_name(name: str) -> str:
    """``test_gate_fails_at_default_threshold`` -> ``Gate fails at default threshold.``"""
    words = name.removeprefix("test_").replace("_", " ").strip()
    return (words[:1].upper() + words[1:] + ".") if words else name


def verifies(
    *partially: str,
    fully: tuple[str, ...] = (),
    test_type: TestType = "requirements-based",
    derivation: Derivation = "requirements-analysis",
) -> Callable[[type], type]:
    """Class decorator: every ``test_*`` method verifies the given requirement ids.

    Methods without a docstring get a description derived from their name; an
    explicit docstring always wins.
    """
    if not partially and not fully:
        raise ValueError("verifies() needs at least one requirement id")

    def decorate(cls: type) -> type:
        for name, member in list(vars(cls).items()):
            if not name.startswith("test_") or not callable(member):
                continue
            if not (member.__doc__ or "").strip():
                member.__doc__ = _description_from_name(name)
            annotated = add_test_properties(
                partially_verifies=list(partially) or None,
                fully_verifies=list(fully) or None,
                test_type=test_type,
                derivation_technique=derivation,
            )(member)
            setattr(cls, name, annotated)
        return cls

    return decorate
