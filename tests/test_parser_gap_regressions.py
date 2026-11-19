"""Regression tests for parser inputs that once leaked a plain exception
(``ValueError``, ``RuntimeError``, ``zipfile.BadZipFile``,
``tokenize.TokenError``) instead of ``PackageError`` (issue #86). Each is a
minimal, hand-crafted adversarial package that must now be rejected with
``PackageError``.
"""

from __future__ import annotations

import io
import struct

import matplotlib.pyplot as plt
import numpy as np
import pytest

from matplotlib_extension.package import (
    PackageError,
    dump_package,
    inspect_package,
    load_package,
)
from tests.fuzz_support import (
    package_files,
    patch_figure_json,
    resign_manifest,
    valid_package_files,
    widen_local_header_filename_length,
    write_package,
)


def _assert_rejected(payload: bytes) -> None:
    with pytest.raises(PackageError):
        load_package(payload)


def test_invalid_linestyle_is_rejected() -> None:
    files = valid_package_files()
    patch_figure_json(
        files,
        lambda spec: spec["axes"][0]["lines"][0].__setitem__(
            "linestyle", "not-a-real-linestyle"
        ),
    )
    _assert_rejected(write_package(files))


def test_invalid_fontweight_is_rejected() -> None:
    files = valid_package_files()
    patch_figure_json(
        files,
        lambda spec: spec["axes"][0]["title"].__setitem__(
            "fontweight", "not-a-real-weight"
        ),
    )
    _assert_rejected(write_package(files))


def test_mismatched_xdata_ydata_length_is_rejected() -> None:
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

    _assert_rejected(write_package(files))


def test_npy_bytes_shaped_like_a_zip_is_rejected() -> None:
    files = valid_package_files()
    array_name = next(name for name in files if name.startswith("arrays/"))
    files[array_name] = b"PK\x03\x04"
    resign_manifest(files)

    _assert_rejected(write_package(files))


def test_scalar_xdata_is_rejected() -> None:
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

    _assert_rejected(write_package(files))


def test_mismatched_local_header_filename_is_rejected() -> None:
    files = valid_package_files()
    payload = widen_local_header_filename_length(
        write_package(files), "manifest.json", extra_bytes=16
    )
    with pytest.raises(PackageError):
        inspect_package(payload)


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


def test_syntactically_broken_npy_header_is_rejected() -> None:
    files = valid_package_files()
    array_name = next(name for name in files if name.startswith("arrays/"))
    files[array_name] = _build_npy_with_raw_header(
        "{'descr': '<f8', 'fortran_order': False, 'shape': (0,}"
    )
    resign_manifest(files)

    _assert_rejected(write_package(files))


def _npy_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def _scatter_and_image_package() -> dict[str, bytes]:
    fig, ax = plt.subplots()
    ax.scatter([1, 2, 3], [1, 2, 3], s=[10, 20, 30], c=[1, 2, 3], cmap="viridis")
    ax.imshow(np.arange(12.0).reshape(3, 4))
    try:
        return package_files(dump_package(fig))
    finally:
        plt.close(fig)


@pytest.mark.parametrize(
    "bad_array",
    [np.array([]), np.array(1.0), np.zeros((2, 2)), np.arange(5.0), np.array([1j] * 3)],
    ids=["empty", "scalar", "2d", "wrong-length", "complex"],
)
def test_wrong_scatter_or_image_arrays_are_rejected(bad_array: np.ndarray) -> None:
    # Every referenced array in turn is replaced; whichever ones feed
    # scatter()/imshow() must fail as PackageError, never a bare
    # ValueError/TypeError from Matplotlib.
    base = _scatter_and_image_package()
    for name in (n for n in base if n.startswith("arrays/")):
        files = dict(base)
        files[name] = _npy_bytes(bad_array)
        resign_manifest(files)
        try:
            figure = load_package(write_package(files))
        except PackageError:
            continue
        plt.close(figure)
