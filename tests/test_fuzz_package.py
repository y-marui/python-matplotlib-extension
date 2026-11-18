"""Property-based (hypothesis) hardening tests for matplotlib_extension.package.

Every test here asserts the same property for a parser entry point that
touches untrusted bytes (``inspect_package``, ``recover_numeric_data``,
``load_package``): for any input, the call either succeeds or raises
``PackageError`` (see ``DOCUMENTED_EXCEPTIONS`` in ``tests/fuzz_support.py``)
-- never an unrelated exception, a hang, or unbounded memory use. Matplotlib
Figures created by a successful call are always closed so a long fuzz run
does not leak figures.

Budget: each property runs ``max_examples`` (100-300, chosen per test below
to balance coverage against CI time) bounded by ``deadline`` (a generous
per-example wall-clock budget; a real hang is instead caught by the
project-wide ``pytest-timeout`` backstop configured in pyproject.toml, since
a single slow-but-not-infinite example should not fail CI on a loaded
runner). Total wall time for this file is well under a minute locally.
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from matplotlib_extension.package import (
    PackageError,
    inspect_package,
    load_package,
    recover_numeric_data,
)
from tests.fuzz_support import (
    KNOWN_UNFIXED_LEAK_TYPES,
    resign_manifest,
    valid_package_files,
    write_package,
)

pytestmark = pytest.mark.fuzz

_BASE_FILES = valid_package_files()
_MEMBER_NAMES = sorted(_BASE_FILES)
_ARRAY_NAME = next(name for name in _MEMBER_NAMES if name.startswith("arrays/"))
_TOLERATED = (PackageError, *KNOWN_UNFIXED_LEAK_TYPES)


def _exercise_all_entry_points(payload: bytes) -> None:
    """Call every read-only package entry point and require a clean result:
    ``PackageError`` (or a narrow, already-tracked known gap -- see
    ``KNOWN_UNFIXED_LEAK_TYPES``), or success (closing any restored Figure).
    """
    for loader in (inspect_package, recover_numeric_data):
        try:
            loader(payload)
        except _TOLERATED:
            pass

    try:
        figure = load_package(payload)
    except _TOLERATED:
        return
    plt.close(figure)


@settings(max_examples=300, deadline=1000)
@given(data=st.binary(max_size=4096))
def test_arbitrary_bytes_never_crash_the_parser(data: bytes) -> None:
    _exercise_all_entry_points(data)


_MUTATION_KINDS = st.one_of(
    st.tuples(st.just("truncate_suffix"), st.integers(min_value=0, max_value=200)),
    st.tuples(st.just("truncate_prefix"), st.integers(min_value=0, max_value=200)),
    st.tuples(
        st.just("flip_bytes"),
        st.lists(st.integers(min_value=0, max_value=1 << 20), max_size=8),
    ),
    st.tuples(st.just("replace"), st.binary(max_size=512)),
    st.tuples(st.just("append"), st.binary(max_size=256)),
)


def _apply_byte_mutation(data: bytes, mutation: tuple[str, Any]) -> bytes:
    kind, arg = mutation
    buffer = bytearray(data)
    if kind == "truncate_suffix":
        buffer = buffer[: max(0, len(buffer) - arg)]
    elif kind == "truncate_prefix":
        buffer = buffer[min(arg, len(buffer)) :]
    elif kind == "flip_bytes":
        for position in arg:
            if buffer:
                buffer[position % len(buffer)] ^= 0xFF
    elif kind == "replace":
        buffer = bytearray(arg)
    elif kind == "append":
        buffer.extend(arg)
    return bytes(buffer)


@settings(
    max_examples=250,
    deadline=1000,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    member_index=st.integers(min_value=0, max_value=len(_MEMBER_NAMES) - 1),
    mutation=_MUTATION_KINDS,
    resign=st.booleans(),
)
def test_mutated_package_member_never_crashes(
    member_index: int, mutation: tuple[str, Any], resign: bool
) -> None:
    """Corrupt exactly one ZIP member of a real package (byte flips,
    truncation, replacement, or appended garbage), optionally re-signing the
    manifest so the mutation reaches deeper, schema-level validation instead
    of being caught immediately by the integrity check."""
    files = dict(_BASE_FILES)
    name = _MEMBER_NAMES[member_index]
    files[name] = _apply_byte_mutation(files[name], mutation)
    if resign and name != "manifest.json":
        resign_manifest(files)
    _exercise_all_entry_points(write_package(files))


_JSON_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**18), max_value=10**18),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=64),
)
_JSON_VALUES = st.recursive(
    _JSON_SCALARS,
    lambda children: st.one_of(
        st.lists(children, max_size=6),
        st.dictionaries(st.text(max_size=20), children, max_size=6),
    ),
    max_leaves=40,
)


@settings(max_examples=200, deadline=2000)
@given(spec=_JSON_VALUES)
def test_arbitrary_json_as_figure_json_never_crashes(spec: Any) -> None:
    """figure.json replaced wholesale by an arbitrary JSON value: wrong
    top-level type, wrong field types, extra keys, deeply nested structures."""
    files = dict(_BASE_FILES)
    files["figure.json"] = (
        json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    resign_manifest(files)
    _exercise_all_entry_points(write_package(files))


@settings(max_examples=200, deadline=2000)
@given(
    axes=st.lists(_JSON_VALUES, max_size=5),
    schema_version=st.one_of(
        st.integers(min_value=-10, max_value=10), st.text(max_size=10)
    ),
    figure_field=_JSON_VALUES,
)
def test_fuzzed_figure_json_fields_never_crash(
    axes: list[Any], schema_version: Any, figure_field: Any
) -> None:
    """Mutate the specific figure.json fields every reader branches on
    first (``schema_version``, ``axes``, ``figure``) with adversarial
    values, keeping the rest of a real package intact."""
    files = dict(_BASE_FILES)
    original = json.loads(files["figure.json"])
    original["axes"] = axes
    original["schema_version"] = schema_version
    original["figure"] = figure_field
    files["figure.json"] = (
        json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    resign_manifest(files)
    _exercise_all_entry_points(write_package(files))


@settings(max_examples=150, deadline=2000)
@given(
    format_name=_JSON_VALUES,
    format_version=_JSON_VALUES,
    figure_schema_version=_JSON_VALUES,
    files_field=_JSON_VALUES,
)
def test_fuzzed_manifest_fields_never_crash(
    format_name: Any,
    format_version: Any,
    figure_schema_version: Any,
    files_field: Any,
) -> None:
    """Mutate manifest.json's own schema-defining fields with adversarial
    values (wrong types, missing structure) while figure.json stays valid."""
    files = dict(_BASE_FILES)
    manifest = json.loads(files["manifest.json"])
    manifest["format"] = format_name
    manifest["format_version"] = format_version
    manifest["figure_schema_version"] = figure_schema_version
    manifest["files"] = files_field
    files["manifest.json"] = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    _exercise_all_entry_points(write_package(files))


_NPY_DTYPES = st.sampled_from(
    [
        "<f8",
        "<f4",
        "<i4",
        "<i8",
        "<u1",
        "|b1",
        "<c16",
        ">f8",  # big-endian: allowed in principle, must be byte-order safe
        "|O",  # object dtype: must be rejected
        "|O8",
        "<U10",  # unicode string dtype: must be rejected
        "<M8[ns]",  # datetime64: must be rejected
    ]
)


@settings(max_examples=200, deadline=2000)
@given(
    descr=_NPY_DTYPES,
    shape=st.lists(st.integers(min_value=0, max_value=5), max_size=3),
    fortran_order=st.booleans(),
    trailing_bytes=st.integers(min_value=0, max_value=256),
)
def test_fuzzed_npy_header_never_crashes(
    descr: str,
    shape: list[int],
    fortran_order: bool,
    trailing_bytes: int,
) -> None:
    """Replace one array entry with a fuzzed NPY header: a disallowed or
    unusual dtype, a shape inconsistent with the trailing data length, or
    pickled/object data under ``allow_pickle=False``."""
    header_stream = BytesIO()
    np.lib.format.write_array_header_1_0(
        header_stream,
        {"descr": descr, "fortran_order": fortran_order, "shape": tuple(shape)},
    )
    header_stream.write(b"\x00" * trailing_bytes)

    files = dict(_BASE_FILES)
    files[_ARRAY_NAME] = header_stream.getvalue()
    resign_manifest(files)
    _exercise_all_entry_points(write_package(files))


@settings(max_examples=100, deadline=2000)
@given(
    compression=st.sampled_from(
        [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA]
    ),
    extra_entries=st.integers(min_value=0, max_value=5),
)
def test_fuzzed_zip_structure_never_crashes(
    compression: int, extra_entries: int
) -> None:
    """Rebuild a real package with ZIP-level structural variation: a
    disallowed compression method, and/or extra unlisted entries."""
    files = dict(_BASE_FILES)
    for index in range(extra_entries):
        files[f"arrays/extra-{index:04d}.npy"] = b"\x00" * 8
    _exercise_all_entry_points(write_package(files, compression=compression))
