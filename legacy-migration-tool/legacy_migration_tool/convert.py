"""One-way legacy dill deserialization and canonical re-save.

Deliberately the only module in this project that imports ``dill``, and
only inside :func:`convert_file`, after :mod:`legacy_migration_tool.confirm`
has already gated the run. Output is produced only through
``matplotlib_extension.savefig(..., editable=True)``, the same allowlisted
canonical serializer the main package uses everywhere else; this module
never hand-rolls its own serialization.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.figure
import matplotlib_extension
from matplotlib_extension.container import LEGACY_PDF_ATTACHMENT
from pypdf import PdfReader


class LegacyConversionError(RuntimeError):
    """Raised when a declared input cannot be read as a legacy figure."""


def _read_legacy_attachment(path: Path) -> bytes:
    """Pull the raw legacy object-stream bytes out of a ``.plt.pdf``.

    This only parses PDF container structure to locate the attachment
    named :data:`LEGACY_PDF_ATTACHMENT`; it never deserializes it.
    """
    try:
        reader = PdfReader(str(path), strict=True)
        attachments = reader.attachments.get(LEGACY_PDF_ATTACHMENT)
    except Exception as exc:
        raise LegacyConversionError(f"{path}: not a readable PDF file") from exc
    if not attachments:
        raise LegacyConversionError(
            f"{path}: no '{LEGACY_PDF_ATTACHMENT}' attachment found; this "
            "tool only converts recognized legacy files"
        )
    if len(attachments) != 1:
        raise LegacyConversionError(
            f"{path}: expected exactly one '{LEGACY_PDF_ATTACHMENT}' attachment"
        )
    return attachments[0]


def _canonical_stem(input_path: Path) -> str:
    """Drop a trailing ``.plt`` suffix so output reads ``name.mpl.png``."""
    name = input_path.name
    if name.lower().endswith(".plt.pdf"):
        return name[: -len(".plt.pdf")]
    return input_path.stem


def convert_file(input_path: Path, output_dir: Path) -> Path:
    """Convert one legacy ``.plt.pdf`` file to a safe ``.mpl.png``.

    Must only be called after :func:`legacy_migration_tool.confirm.confirm_once`
    has already granted confirmation for this process. Imports ``dill``
    locally, at call time, so merely importing this module never pulls
    in the arbitrary-code-execution risk.

    Args:
        input_path: A legacy ``.plt.pdf`` file containing a
            ``fig.dill`` attachment.
        output_dir: The single dedicated directory to write into.

    Returns:
        The path to the newly written ``.mpl.png`` file.

    Raises:
        LegacyConversionError: The input is not a recognized legacy file,
            or its object stream does not deserialize to a Matplotlib
            ``Figure``.
    """
    import dill  # noqa: PLC0415 - intentionally local; see module docstring

    blob = _read_legacy_attachment(input_path)
    try:
        fig = dill.loads(blob)
    except Exception as exc:
        raise LegacyConversionError(
            f"{input_path}: legacy object stream failed to deserialize"
        ) from exc
    if not isinstance(fig, matplotlib.figure.Figure):
        raise LegacyConversionError(
            f"{input_path}: legacy object stream is not a Matplotlib Figure"
        )

    output_path = output_dir / f"{_canonical_stem(input_path)}.mpl.png"
    matplotlib_extension.savefig(fig, output_path, editable=True, mode="x")
    return output_path
