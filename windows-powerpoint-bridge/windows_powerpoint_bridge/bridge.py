"""Extraction-only orchestration: selection -> OLE part -> ``figure.mpl.png``.

This is the only module that writes a destination file. It never
restores a Figure, never evaluates or executes anything from the
presentation, and never uploads the presentation anywhere -- it reads
PowerPoint's current selection
(:mod:`windows_powerpoint_bridge.com_selection`), resolves that
selection to one embedded OLE part's bytes
(:mod:`windows_powerpoint_bridge.relationship`), and hands those bytes
to ``matplotlib_extension.pyplot.extract_editable_png()``, the same
validated boundary function the macOS bridge (issue #77) uses. That
function -- not this one -- performs every PNG/OLE signature and
``figure.mpl.png`` suffix check.

Generic PowerPoint ``Shape.Export(path, ppShapeFormatPNG)`` ("Save as
Picture") was empirically confirmed (against a real Windows machine,
see the handoff notes) to NOT preserve the embedded native file: it
re-renders the shape instead, producing a PNG with a different
SHA-256 than the real embedded ``figure.mpl.png``. That is why this
module exists rather than this bridge being a thin wrapper around a
standard PowerPoint export verb.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from matplotlib_extension.package import PackageError
from matplotlib_extension.pyplot import extract_editable_png

from windows_powerpoint_bridge.com_selection import ALLOWED_SHAPE_TYPE, read_selection
from windows_powerpoint_bridge.errors import BridgeError
from windows_powerpoint_bridge.relationship import (
    MAX_PRESENTATION_BYTES,
    resolve_ole_part,
)


def _read_presentation_bytes(path: str) -> bytes:
    presentation_path = Path(path)
    try:
        size = presentation_path.stat().st_size
    except OSError as exc:
        raise BridgeError(f"Unable to read presentation at {path}: {exc}") from exc
    if size > MAX_PRESENTATION_BYTES:
        raise BridgeError("Presentation package exceeds the size limit")
    try:
        return presentation_path.read_bytes()
    except OSError as exc:
        raise BridgeError(f"Unable to read presentation at {path}: {exc}") from exc


def extract_selected_figure(destination: Path | str, *, mode: str = "x") -> Path:
    """Extract the currently selected PowerPoint shape's editable PNG.

    Args:
        destination: Destination path ending in ``.mpl.png``.
        mode: ``"x"`` for exclusive creation or ``"w"`` for atomic
            overwrite, forwarded to
            ``matplotlib_extension.pyplot.extract_editable_png()``.

    Returns:
        The destination path, on success.

    Raises:
        BridgeError: If the selection, presentation state, or embedded
            package structure is not exactly what this bridge allowlists.
        matplotlib_extension.package.PackageError: If the resolved OLE
            part is not a validly structured editable PNG container.
    """
    selection = read_selection()
    if selection.shape_type != ALLOWED_SHAPE_TYPE:
        raise BridgeError(
            f"Selected shape is not an embedded OLE object (got shape type "
            f"{selection.shape_type!r})"
        )

    pptx_bytes = _read_presentation_bytes(selection.presentation_path)
    ole_bytes = resolve_ole_part(
        pptx_bytes,
        slide_index=selection.slide_index,
        shape_name=selection.shape_name,
    )

    destination_path = Path(destination)
    descriptor, temp_name = tempfile.mkstemp(
        dir=destination_path.parent, prefix=".windows-powerpoint-bridge.", suffix=".bin"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(ole_bytes)
        extract_editable_png(temp_path, destination_path, mode=mode)
    except PackageError:
        raise
    finally:
        temp_path.unlink(missing_ok=True)
    return destination_path
