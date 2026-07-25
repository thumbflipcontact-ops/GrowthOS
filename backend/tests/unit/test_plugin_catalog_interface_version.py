"""See docs/plugins/PLUGIN_ARCHITECTURE.md §"Interface versioning". Covers
_interface_version_is_compatible in isolation; end-to-end discovery behavior (a plugin with
an incompatible version being excluded from the catalog) is covered by
backend/tests/integration/test_plugin_catalog_and_registry.py."""

from __future__ import annotations

import pytest

from app.core.plugin_catalog import CORE_INTERFACE_VERSION, _interface_version_is_compatible


def test_same_version_is_compatible() -> None:
    assert _interface_version_is_compatible(CORE_INTERFACE_VERSION) is True


def test_same_major_different_minor_is_compatible() -> None:
    major = CORE_INTERFACE_VERSION.split(".", 1)[0]
    assert _interface_version_is_compatible(f"{major}.99") is True


def test_different_major_is_incompatible() -> None:
    major = int(CORE_INTERFACE_VERSION.split(".", 1)[0])
    assert _interface_version_is_compatible(f"{major + 1}.0") is False


@pytest.mark.parametrize("garbage", ["not-a-version", "", "v1.0", "1.0.0-beta"])
def test_malformed_version_is_incompatible_or_handled_gracefully(garbage: str) -> None:
    # "1.0.0-beta" has a parseable major component (1) so it IS treated as compatible — only
    # the major component before the first "." is inspected, by design (see the function's
    # docstring). The others have no parseable leading integer and must not raise.
    result = _interface_version_is_compatible(garbage)
    assert isinstance(result, bool)
