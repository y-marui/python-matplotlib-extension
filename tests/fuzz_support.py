"""Shared helpers for property-based (hypothesis) and fixture-based parser
hardening tests.

Not a test module itself (no ``test_`` prefix, so pytest does not collect it).
"""

from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from io import BytesIO
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from matplotlib_extension.package import PackageError, dump_package

# Every property test below asserts against exactly this set: a parser entry
# point touching untrusted bytes must either succeed or raise one of these,
# never anything else (a crash, a hang, or unbounded memory use). This is the
# *documented*, intended contract (see docs/EDITABLE_FORMAT.md's Security
# Boundary section).
DOCUMENTED_EXCEPTIONS: tuple[type[BaseException], ...] = (PackageError,)

# Parser gaps the fuzz suite once found (issue #86) are fixed: every reader
# now raises only ``PackageError`` on malformed input. These tuples are kept,
# empty, so the property tests keep one place to tolerate a newly discovered,
# not-yet-fixed leak -- add the exception type here together with a pinned
# ``xfail`` reproduction, and remove it again when the leak is fixed.
ARRAY_LOAD_LEAK_TYPES: tuple[type[BaseException], ...] = ()
ZIP_STRUCTURE_LEAK_TYPES: tuple[type[BaseException], ...] = ()
ARTIST_RESTORE_LEAK_TYPES: tuple[type[BaseException], ...] = ()


def simple_figure() -> Figure:
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0, 2.0], [2.0, 3.0, 1.5])
    ax.scatter([0.0, 1.0], [1.0, 0.0], s=[5.0, 6.0], c="red", label="pts")
    ax.set_title("fuzz target figure")
    return fig


def package_files(payload: bytes) -> dict[str, bytes]:
    """Split a canonical ZIP payload into its member files."""
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def write_package(
    files: dict[str, bytes], *, compression: int = zipfile.ZIP_STORED
) -> bytes:
    """Reassemble member files into a ZIP (without re-validating contents)."""
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


def valid_package_files() -> dict[str, bytes]:
    """A real, valid package's member files, for use as a mutation seed."""
    fig = simple_figure()
    try:
        payload = dump_package(fig)
    finally:
        plt.close(fig)
    return package_files(payload)


def resign_manifest(files: dict[str, bytes]) -> None:
    """Recompute every manifest.json file record after mutating a member.

    Mutates ``files`` in place. Keeps the manifest internally consistent
    (sizes/digests match) so a test can isolate exactly one deliberate
    inconsistency instead of tripping the integrity check incidentally.
    """
    manifest = json.loads(files["manifest.json"])
    for record in manifest["files"]:
        path = record["path"]
        if path in files:
            data = files[path]
            record["size"] = len(data)
            record["sha256"] = hashlib.sha256(data).hexdigest()
    files["manifest.json"] = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def patch_figure_json(files: dict[str, bytes], mutate: Any) -> None:
    """Apply ``mutate(spec_dict)`` to figure.json and resign the manifest."""
    spec = json.loads(files["figure.json"])
    mutate(spec)
    files["figure.json"] = (
        json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    resign_manifest(files)


def inflate_declared_entry_size(
    payload: bytes, member: str, declared_size: int
) -> bytes:
    """Rewrite *payload*'s local+central directory records for *member* so
    both claim ``declared_size`` bytes, without changing the actual bytes on
    disk.

    This reproduces a plausible attack: a crafted ZIP central directory can
    claim an entry is far larger than the bytes actually present. It lets a
    test exercise the project's documented "reject oversized entries before
    reading them" resource limit with a tiny fixture file, instead of
    committing a multi-hundred-megabyte binary just to exceed the limit for
    real.
    """
    data = bytearray(payload)
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        info = archive.getinfo(member)
        local_offset = info.header_offset

    # Local file header: sig(4) ver(2) flags(2) method(2) time(2) date(2)
    # crc32(4) compressed_size(4) uncompressed_size(4) name_len(2) extra_len(2)
    struct.pack_into("<I", data, local_offset + 18, declared_size)
    struct.pack_into("<I", data, local_offset + 22, declared_size)

    # Central directory record for the same entry: scan every "PK\x01\x02"
    # record and match by filename, since zipfile does not expose its offset.
    # Central directory file header layout (fixed 46-byte prefix):
    #   compressed_size at +20, uncompressed_size at +24,
    #   filename_length at +28, filename starts at +46.
    needle = info.filename.encode("utf-8")
    cd_offset = 0
    found = False
    while True:
        cd_offset = data.find(b"PK\x01\x02", cd_offset)
        if cd_offset < 0:
            break
        name_length = struct.unpack_from("<H", data, cd_offset + 28)[0]
        candidate = bytes(data[cd_offset + 46 : cd_offset + 46 + name_length])
        if candidate == needle:
            struct.pack_into("<I", data, cd_offset + 20, declared_size)
            struct.pack_into("<I", data, cd_offset + 24, declared_size)
            found = True
            break
        cd_offset += 4
    if not found:
        raise AssertionError(f"central directory record for {member!r} not found")
    return bytes(data)


def widen_local_header_filename_length(
    payload: bytes, member: str, extra_bytes: int
) -> bytes:
    """Widen *member*'s LOCAL file header filename-length field by
    *extra_bytes*, without touching the matching central directory record or
    any actual file content.

    This reproduces ``ZIP_STRUCTURE_LEAK_TYPES`` deterministically: the
    local header's filename field (now longer than the real name) no longer
    matches the central directory's recorded filename, which zipfile only
    notices lazily -- when the entry is actually read -- raising a bare
    ``zipfile.BadZipFile`` ("File name in directory ... and header ...
    differ") instead of the project's own ``PackageError``.
    """
    data = bytearray(payload)
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        info = archive.getinfo(member)
        local_offset = info.header_offset

    # Local file header: filename_len at +26 (2 bytes, little-endian).
    filename_len = struct.unpack_from("<H", data, local_offset + 26)[0]
    struct.pack_into("<H", data, local_offset + 26, filename_len + extra_bytes)
    return bytes(data)
