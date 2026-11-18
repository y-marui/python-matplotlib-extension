"""Property-based (hypothesis) hardening tests for
matplotlib_extension.container: the PNG/PDF/SVG/OLE container bindings.

Unlike tests/test_fuzz_package.py, these entry points are held to
``PackageError``-or-nothing with only one narrow, already-tracked exemption:
``ZIP_STRUCTURE_LEAK_TYPES`` (see ``tests/fuzz_support.py``), since every
extractor here validates its result through ``inspect_package`` before
returning and so inherits that specific gap too. None of the *other* known
gaps (artist restoration, array loading) live anywhere container.py's
extractors touch, so widening tolerance beyond that one shared gap would
just hide a real new leak in this module. A successful extraction must also
itself be a validly usable package -- extracting "successfully" into
something that gap-free validation rejects is itself a bug in the
extractor, not a case to swallow.

Budget: see the module docstring of tests/test_fuzz_package.py for the
rationale behind the chosen ``max_examples``/``deadline`` values.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from matplotlib_extension.container import (
    extract_ole_native_png,
    extract_payload,
    extract_pdf,
    extract_png,
    extract_svg,
)
from matplotlib_extension.package import PackageError, inspect_package
from matplotlib_extension.pyplot import savefig
from tests.fuzz_support import ZIP_STRUCTURE_LEAK_TYPES, simple_figure

pytestmark = pytest.mark.fuzz


def _real_editable_files() -> dict[str, bytes]:
    """One real, valid editable file per container binding, built once."""
    fig = simple_figure()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            files: dict[str, bytes] = {}
            for extension, name in (
                ("png", "figure.mpl.png"),
                ("pdf", "figure.mpl.pdf"),
                ("svg", "figure.mpl.svg"),
            ):
                path = tmp / name
                savefig(fig, path)
                files[extension] = path.read_bytes()

            ole_path = tmp / "figure.ole"
            savefig(fig, ole_path)
            files["ole"] = ole_path.read_bytes()
            return files
    finally:
        plt.close(fig)


_REAL_FILES = _real_editable_files()


def _mutate(data: bytes, mutation: tuple[str, Any]) -> bytes:
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
    elif kind == "insert":
        if buffer:
            position = arg[0] % len(buffer)
            buffer[position:position] = arg[1]
        else:
            buffer.extend(arg[1])
    elif kind == "replace_region":
        if buffer:
            start = arg[0] % len(buffer)
            end = min(len(buffer), start + arg[1])
            buffer[start:end] = arg[2][: end - start]
    return bytes(buffer)


_MUTATION_KINDS = st.one_of(
    st.tuples(st.just("truncate_suffix"), st.integers(min_value=0, max_value=300)),
    st.tuples(st.just("truncate_prefix"), st.integers(min_value=0, max_value=300)),
    st.tuples(
        st.just("flip_bytes"),
        st.lists(st.integers(min_value=0, max_value=1 << 20), max_size=10),
    ),
    st.tuples(
        st.just("insert"),
        st.tuples(st.integers(min_value=0, max_value=1 << 20), st.binary(max_size=64)),
    ),
    st.tuples(
        st.just("replace_region"),
        st.tuples(
            st.integers(min_value=0, max_value=1 << 20),
            st.integers(min_value=0, max_value=64),
            st.binary(max_size=64),
        ),
    ),
)


def _check_ole_native_png(editable_png: bytes) -> None:
    """``extract_ole_native_png`` returns an editable *PNG*, not a canonical
    package, so its success claim must be checked by unwrapping that PNG
    (which itself validates the package it embeds) rather than by handing
    PNG bytes straight to ``inspect_package``."""
    extract_png(editable_png)


# What a *successful* return value from each extractor must satisfy -- the
# extractor's own claim that the bytes it handed back are genuinely usable.
_UNWRAP: dict[Any, Any] = {
    extract_png: inspect_package,
    extract_pdf: inspect_package,
    extract_svg: inspect_package,
    extract_ole_native_png: _check_ole_native_png,
    extract_payload: inspect_package,
}


def _exercise(extractor: Any, data: bytes) -> None:
    try:
        payload = extractor(data)
    except (PackageError, *ZIP_STRUCTURE_LEAK_TYPES):
        return
    # A successful extraction must itself be genuinely valid: if the
    # extractor's own success claim doesn't hold up, that's a bug in the
    # extractor, not something to swallow.
    _UNWRAP[extractor](payload)


@settings(max_examples=250, deadline=1500)
@given(
    binding=st.sampled_from(["png", "pdf", "svg", "ole"]),
    mutation=_MUTATION_KINDS,
)
def test_mutated_container_never_crashes(
    binding: str, mutation: tuple[str, Any]
) -> None:
    extractors = {
        "png": extract_png,
        "pdf": extract_pdf,
        "svg": extract_svg,
        "ole": extract_ole_native_png,
    }
    data = _mutate(_REAL_FILES[binding], mutation)
    _exercise(extractors[binding], data)


@settings(max_examples=250, deadline=1500)
@given(data=st.binary(max_size=4096))
def test_arbitrary_bytes_never_crash_any_extractor(data: bytes) -> None:
    for extractor in (extract_png, extract_pdf, extract_svg, extract_ole_native_png):
        _exercise(extractor, data)


_SIGNATURE_PREFIXES = st.sampled_from(
    [
        b"",
        b"\x89PNG\r\n\x1a\n",
        b"%PDF-",
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        b"PK\x03\x04",
        b"<svg ",
        b"<svg>",
        b"\x89PNG",  # truncated PNG signature
        b"%PDF",  # truncated PDF signature
    ]
)


@settings(max_examples=250, deadline=1500)
@given(prefix=_SIGNATURE_PREFIXES, tail=st.binary(max_size=2048))
def test_extract_payload_dispatch_never_crashes(prefix: bytes, tail: bytes) -> None:
    """``extract_payload`` dispatches purely on signature bytes; a crafted
    prefix must route to the right extractor (or fail cleanly) regardless of
    what garbage follows it."""
    _exercise(extract_payload, prefix + tail)


@settings(max_examples=150, deadline=1500)
@given(
    chunk_type=st.binary(min_size=4, max_size=4),
    chunk_data=st.binary(max_size=256),
    corrupt_crc=st.booleans(),
)
def test_fuzzed_png_chunk_never_crashes(
    chunk_type: bytes, chunk_data: bytes, corrupt_crc: bool
) -> None:
    """Splice an extra, arbitrary PNG chunk (type + data, correct or
    corrupted CRC) into a real editable PNG just before IEND."""
    import struct
    import zlib

    data = bytearray(_REAL_FILES["png"])
    iend_index = data.rfind(b"IEND") - 4
    assert iend_index > 0
    crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
    if corrupt_crc:
        crc ^= 1
    chunk = (
        struct.pack(">I", len(chunk_data))
        + chunk_type
        + chunk_data
        + struct.pack(">I", crc)
    )
    spliced = bytes(data[:iend_index]) + chunk + bytes(data[iend_index:])
    _exercise(extract_png, spliced)


@settings(max_examples=100, deadline=1500)
@given(
    base64_text=st.text(
        alphabet=st.characters(
            whitelist_categories=(),
            whitelist_characters="ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "abcdefghijklmnopqrstuvwxyz0123456789+/=\r\n",
        ),
        max_size=256,
    )
)
def test_fuzzed_svg_base64_payload_never_crashes(base64_text: str) -> None:
    """Replace the base64 payload inside a real editable SVG's metadata with
    arbitrary text drawn from (and outside) the base64 alphabet."""
    import re

    data = _REAL_FILES["svg"]
    replaced = re.sub(
        rb'(encoding="base64">)([A-Za-z0-9+/=\r\n]+)(</mplex:package>)',
        lambda match: match.group(1) + base64_text.encode("ascii") + match.group(3),
        data,
        count=1,
    )
    _exercise(extract_svg, replaced)
