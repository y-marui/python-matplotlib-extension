"""Deterministic-rejection tests for the hand-crafted adversarial fixtures in
tests/fixtures/malformed/.

Each fixture targets one specific, documented rejection path (see
``docs/EDITABLE_FORMAT.md``'s Resource Limits and Security Boundary
sections). This asserts the *exact* exception type and message substring for
each one, not just "raises something" -- see
``tests/fixtures/malformed/generate_fixtures.py`` for how each was built and
which code path it targets.
"""

import json
from pathlib import Path

import pytest

from matplotlib_extension.container import (
    extract_ole_native_png,
    extract_pdf,
    extract_png,
    extract_svg,
)
from matplotlib_extension.package import PackageError, load_package

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "malformed"
LOADERS = {
    "load_package": load_package,
    "extract_png": extract_png,
    "extract_pdf": extract_pdf,
    "extract_svg": extract_svg,
    "extract_ole_native_png": extract_ole_native_png,
}


def _load_index() -> list[dict[str, str]]:
    return json.loads((FIXTURES_DIR / "index.json").read_text())


@pytest.mark.parametrize("entry", _load_index(), ids=lambda entry: entry["file"])
def test_malformed_fixture_is_rejected_deterministically(
    entry: dict[str, str],
) -> None:
    payload = (FIXTURES_DIR / entry["file"]).read_bytes()
    loader = LOADERS[entry["loader"]]

    with pytest.raises(PackageError, match=entry["error"]):
        loader(payload)


def test_fixture_index_matches_files_on_disk() -> None:
    indexed_names = {entry["file"] for entry in _load_index()}
    actual_names = {
        path.name for path in FIXTURES_DIR.iterdir() if path.suffix == ".bin"
    }
    assert indexed_names == actual_names


def test_every_fixture_is_rejected_the_same_way_twice() -> None:
    """Rejection must be a pure function of the bytes: no stateful parser
    quirk should make a second parse of the same malformed input behave
    differently from the first (e.g. partial mutation of shared state)."""
    for entry in _load_index():
        payload = (FIXTURES_DIR / entry["file"]).read_bytes()
        loader = LOADERS[entry["loader"]]
        errors = []
        for _ in range(2):
            with pytest.raises(PackageError) as excinfo:
                loader(payload)
            errors.append(str(excinfo.value))
        assert errors[0] == errors[1]
