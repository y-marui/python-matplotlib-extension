"""Pinned, minimal reproductions of parser gaps this fuzz-hardening PR found
but, per its scope (no edits to matplotlib_extension/package.py or
container.py), does not fix.

Each is marked ``xfail(strict=True)``: if one of these ever starts raising
``PackageError`` instead of leaking a raw exception, this file turns into a
hard failure telling you to narrow ``ARRAY_LOAD_LEAK_TYPES``/
``ARTIST_RESTORE_LEAK_TYPES`` in ``tests/fuzz_support.py`` and delete the
corresponding ``xfail`` -- so a real fix can't silently stay unnoticed by the
fuzz suite.

The ``xfail(raises=...)`` decorator alone is not enough for that: every one
of these gaps' "fixed" form is ``PackageError``, which is itself a
``ValueError`` subclass, so a fix that raises ``PackageError`` would still
satisfy e.g. ``raises=ValueError`` and the test would keep reporting a quiet
XFAIL forever. Each test body therefore explicitly catches ``PackageError``
first and calls ``pytest.fail`` (an exception the ``raises=`` decorator does
not match, so it is reported as a genuine failure regardless of
``strict``) -- only a *different* exception type is left to propagate out
and satisfy the decorator's ``raises=``.

See the PR description for the full writeup of each gap and a suggested
follow-up issue.
"""

from __future__ import annotations

import io
import struct
import tokenize
import zipfile

import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.figure import Figure

from matplotlib_extension.package import PackageError, inspect_package, load_package
from tests.fuzz_support import (
    patch_figure_json,
    resign_manifest,
    valid_package_files,
    widen_local_header_filename_length,
    write_package,
)


def _load_unless_fixed(payload: bytes) -> Figure:
    """Call ``load_package``, but fail loudly -- bypassing ``xfail`` --
    if the gap under test has actually been fixed to raise ``PackageError``.
    See this module's docstring for why ``xfail(raises=...)`` alone can't
    detect that (``PackageError`` is itself a ``ValueError`` subclass)."""
    try:
        return load_package(payload)
    except PackageError:
        pytest.fail(
            "this gap appears fixed: load_package now raises PackageError. "
            "Narrow ARRAY_LOAD_LEAK_TYPES/ARTIST_RESTORE_LEAK_TYPES in "
            "tests/fuzz_support.py and delete this xfail."
        )


@pytest.mark.xfail(
    raises=ValueError,
    strict=True,
    reason=(
        "_restore_line (package.py) only bounds-checks `linestyle` as a "
        "string (<=100 chars); it never validates it against Matplotlib's "
        "own allowed linestyle values before passing it to Line2D(), unlike "
        "every other enum-shaped field on the same object (dash_capstyle, "
        "dash_joinstyle, drawstyle). An invalid value leaks a bare "
        "ValueError from Matplotlib instead of PackageError."
    ),
)
def test_invalid_linestyle_leaks_plain_valueerror() -> None:
    files = valid_package_files()
    patch_figure_json(
        files,
        lambda spec: spec["axes"][0]["lines"][0].__setitem__(
            "linestyle", "not-a-real-linestyle"
        ),
    )
    figure = _load_unless_fixed(write_package(files))
    plt.close(figure)


@pytest.mark.xfail(
    raises=ValueError,
    strict=True,
    reason=(
        "_apply_text_spec (package.py) only type-checks `fontweight` "
        "(str/int/float, not bool); it never validates a string value "
        "against Matplotlib's known font weight names before calling "
        "Text.set_fontweight(). An invalid value leaks a bare ValueError "
        "from Matplotlib instead of PackageError."
    ),
)
def test_invalid_fontweight_leaks_plain_valueerror() -> None:
    files = valid_package_files()
    patch_figure_json(
        files,
        lambda spec: spec["axes"][0]["title"].__setitem__(
            "fontweight", "not-a-real-weight"
        ),
    )
    figure = _load_unless_fixed(write_package(files))
    plt.close(figure)


@pytest.mark.xfail(
    raises=ValueError,
    strict=True,
    reason=(
        "_restore_line (package.py) loads `xdata`/`ydata` as two "
        "independent array references and never checks they have the same "
        "length before constructing Line2D(xdata, ydata, ...). A crafted "
        "package with mismatched lengths leaks a bare ValueError from "
        "Matplotlib's internal broadcasting (Axes.add_line -> "
        "Line2D.recache -> numpy.broadcast_arrays) instead of PackageError. "
        "Likely not unique to Line2D -- the scatter/image restore paths "
        "also load several independently-referenced arrays "
        "(offsets/sizes/linewidths/edgecolor; data/extent) without an "
        "explicit cross-length check, though Matplotlib's own `scatter`/"
        "`imshow` may happen to validate some of those combinations itself."
    ),
)
def test_mismatched_xdata_ydata_length_leaks_plain_valueerror() -> None:
    files = valid_package_files()
    xdata_path = None

    def record_xdata_path(spec: dict) -> None:
        nonlocal xdata_path
        xdata_path = spec["axes"][0]["lines"][0]["xdata"]

    patch_figure_json(files, record_xdata_path)
    assert xdata_path is not None

    empty_array = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        empty_array, {"descr": "<f8", "fortran_order": False, "shape": (0,)}
    )
    files[xdata_path] = empty_array.getvalue()
    resign_manifest(files)

    figure = _load_unless_fixed(write_package(files))
    plt.close(figure)


@pytest.mark.xfail(
    raises=zipfile.BadZipFile,
    strict=True,
    reason=(
        "_load_array (package.py) only catches (OSError, ValueError, "
        "EOFError) around numpy.load(). numpy.load() falls back to opening "
        "the stream as a zip (.npz) archive whenever it does not start with "
        "the plain .npy magic; array bytes that happen to start with the "
        "ZIP local-file-header signature (PK\\x03\\x04) but are not a valid "
        "zip leak a bare zipfile.BadZipFile, which is not a subclass of any "
        "of those three caught types."
    ),
)
def test_npy_bytes_shaped_like_a_zip_leak_plain_badzipfile() -> None:
    files = valid_package_files()
    array_name = next(name for name in files if name.startswith("arrays/"))
    files[array_name] = b"PK\x03\x04"
    resign_manifest(files)

    figure = _load_unless_fixed(write_package(files))
    plt.close(figure)


@pytest.mark.xfail(
    raises=RuntimeError,
    strict=True,
    reason=(
        "_restore_line (package.py) never checks that xdata/ydata are "
        "1-dimensional before constructing Line2D(). A 0-d (scalar) array "
        "is a valid, allowlisted dtype/shape combination for _load_array, "
        "but Line2D.__init__ rejects it with a bare RuntimeError "
        "('xdata must be a sequence') since a 0-d array is not iterable -- "
        "a different leaked exception type from the same missing-"
        "cross-validation root cause as the shape-mismatch ValueError case "
        "above."
    ),
)
def test_scalar_xdata_leaks_plain_runtimeerror() -> None:
    files = valid_package_files()
    xdata_path = None

    def record_xdata_path(spec: dict) -> None:
        nonlocal xdata_path
        xdata_path = spec["axes"][0]["lines"][0]["xdata"]

    patch_figure_json(files, record_xdata_path)
    assert xdata_path is not None

    scalar_array = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        scalar_array, {"descr": "<f8", "fortran_order": False, "shape": ()}
    )
    scalar_array.write(struct.pack("<d", 0.0))
    files[xdata_path] = scalar_array.getvalue()
    resign_manifest(files)

    figure = _load_unless_fixed(write_package(files))
    plt.close(figure)


@pytest.mark.xfail(
    raises=zipfile.BadZipFile,
    strict=True,
    reason=(
        "_validated_files (package.py) -- the shared ZIP-structure "
        "validator behind every reader, and transitively every "
        "container.py extractor -- only wraps the zipfile.ZipFile(...) "
        "constructor call in try/except zipfile.BadZipFile. zipfile's own "
        "lazy consistency check (comparing a local file header against its "
        "central directory record) only runs when the entry is actually "
        "read, a few lines later and outside that try/except, so a ZIP "
        "whose central directory parses fine but disagrees with a local "
        "header leaks a bare zipfile.BadZipFile ('File name in directory "
        "... and header ... differ') instead of PackageError. This is the "
        "broadest of the gaps this suite found: it is reachable from "
        "inspect_package directly, not only from load_package."
    ),
)
def test_mismatched_local_header_filename_leaks_plain_badzipfile() -> None:
    files = valid_package_files()
    payload = widen_local_header_filename_length(
        write_package(files), "manifest.json", extra_bytes=16
    )
    try:
        inspect_package(payload)
    except PackageError:
        pytest.fail(
            "this gap appears fixed: inspect_package now raises "
            "PackageError. Narrow ZIP_STRUCTURE_LEAK_TYPES in "
            "tests/fuzz_support.py and delete this xfail."
        )


def _build_npy_with_raw_header(header_text: str) -> bytes:
    """A low-level .npy blob with an exact, hand-written header string,
    bypassing numpy's own header-writing validation entirely."""
    header_bytes = header_text.encode("latin1")
    preamble_len = 6 + 2 + 2  # magic(6) + version(2) + v1.0 header-length field(2)
    padding = (-(preamble_len + len(header_bytes) + 1)) % 64
    header_bytes += b" " * padding + b"\n"
    buffer = io.BytesIO()
    buffer.write(b"\x93NUMPY")
    buffer.write(bytes([1, 0]))
    buffer.write(struct.pack("<H", len(header_bytes)))
    buffer.write(header_bytes)
    return buffer.getvalue()


@pytest.mark.xfail(
    raises=tokenize.TokenError,
    strict=True,
    reason=(
        "_load_array (package.py) catches (OSError, ValueError, EOFError) "
        "around numpy.load(). NumPy's own .npy header parser "
        "(numpy.lib.format._filter_header) reconstructs the header with "
        "Python's `tokenize` module and can itself raise "
        "tokenize.TokenError for a header string that is syntactically "
        "broken (e.g. an unterminated bracket) rather than merely "
        "containing a disallowed dtype -- a failure mode outside all three "
        "caught exception types."
    ),
)
def test_syntactically_broken_npy_header_leaks_tokenerror() -> None:
    files = valid_package_files()
    array_name = next(name for name in files if name.startswith("arrays/"))
    files[array_name] = _build_npy_with_raw_header(
        "{'descr': '<f8', 'fortran_order': False, 'shape': (0,}"
    )
    resign_manifest(files)

    figure = _load_unless_fixed(write_package(files))
    plt.close(figure)
