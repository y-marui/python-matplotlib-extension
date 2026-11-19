"""Read-only COM queries against PowerPoint for Windows's live selection.

Every call here only reads state: the current selection, the shape and
slide it resolves to, and the owning presentation's saved status and
path. This module never calls any PowerPoint method that saves,
exports, or otherwise mutates the live, already-open document --
mirroring :mod:`macos_powerpoint_bridge.applescript`'s read-only
boundary (issue #77) for the same reason: an extraction-only bridge
must never risk the live document.

``win32com.client.GetActiveObject("PowerPoint.Application")`` connects
to an *already-running* PowerPoint instance via the Windows Running
Object Table; it never launches a new instance and never opens,
creates, or activates a document. If no instance is running, or the
running instance's ROT registration is not visible to this process,
this raises :class:`~windows_powerpoint_bridge.errors.BridgeError`
rather than falling back to ``Dispatch()``, which would start a new,
empty PowerPoint instance -- exactly the kind of side effect this
bridge must not have.

``win32com``/``pywin32`` is imported lazily, inside
:func:`_get_running_application`, not at module load time. It is a
Windows-only package (see this sub-project's ``pyproject.toml``, which
declares it with a ``sys_platform == "win32"`` marker) and does not
install on macOS/Linux; importing it lazily lets this module -- and
everything that imports it, including the test suite -- load on any
platform, with the actual COM call only ever attempted on Windows.

UNCONFIRMED and the one open question that could force a redesign of
this module (tracked in
`issue #89 <https://github.com/y-marui/python-matplotlib-extension/issues/89>`_):
whether an interactively, user-driven PowerPoint selection on a real
desktop session is visible to ``GetActiveObject`` from the process
that would run this bridge, or whether Windows session isolation (a
different Windows session, e.g. an SSH/service session vs. the
interactive desktop session) hides it. Confirmed so far: calling it
from an SSH/automation session (a different Windows session than the
interactive desktop) fails with ``MK_E_UNAVAILABLE``
(``0x800401E3``) -- expected, and not evidence either way about
same-session use. This bridge is designed to be *run by the end user
from their own interactive session*, at the same time as PowerPoint --
the same session, by construction -- so a same-session
``GetActiveObject`` call should see the Running Object Table entry
PowerPoint registers there regardless of how this question resolves
for a *different*, automation-driven session trying to reach across a
session boundary it was never designed to cross. Issue #89 needs a
session running directly on the Windows machine itself to settle this
with real evidence.

Also UNCONFIRMED: that ``Selection.SlideRange`` resolves correctly for
a ``ppSelectionShapes``-type selection (as opposed to only a
``ppSelectionSlides``-type one). The PowerPoint object model documents
``SlideRange`` as valid for any selection, but this has not been
checked against a real running PowerPoint for Windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from windows_powerpoint_bridge.errors import BridgeError

#: msoShapeType.msoEmbeddedOLEObject -- confirmed against real PowerPoint
#: for Windows via COM (``Shape.Type`` == 7 for the OLE Package object
#: ``save_pptx()`` embeds; see the handoff notes).
ALLOWED_SHAPE_TYPE = 7

#: PpSelectionType.ppSelectionShapes.
_SELECTION_TYPE_SHAPES = 2

_APPLICATION_PROG_ID = "PowerPoint.Application"


@dataclass(frozen=True)
class SelectionInfo:
    """The exactly-one selected shape, and its exactly-one slide."""

    shape_type: int
    shape_name: str
    slide_index: int
    presentation_path: str


def _get_running_application() -> Any:
    try:
        import win32com.client
    except ImportError as exc:
        raise BridgeError(
            "pywin32 is required on Windows to read PowerPoint's selection "
            "(install it with `pip install pywin32` or `uv sync` on Windows)"
        ) from exc
    try:
        return win32com.client.GetActiveObject(_APPLICATION_PROG_ID)
    except Exception as exc:
        # GetActiveObject raises pywintypes.com_error (a plain Exception
        # subclass, not importable without pywin32 itself) when no
        # PowerPoint instance is registered in the Running Object Table --
        # the expected case when PowerPoint isn't open, or (unconfirmed,
        # see module docstring) when session isolation hides it.
        raise BridgeError(
            "Unable to connect to a running PowerPoint for Windows instance "
            f"via COM: {exc}"
        ) from exc


def read_selection() -> SelectionInfo:
    """Read the current PowerPoint-for-Windows selection, read-only.

    Raises:
        BridgeError: If PowerPoint cannot be reached via COM, the
            selection is not exactly one shape on exactly one slide,
            the presentation has unsaved changes, or any value COM
            returns is not in the exact shape this function expects.
    """
    application = _get_running_application()
    try:
        window = application.ActiveWindow
    except Exception as exc:
        raise BridgeError(f"Unable to read PowerPoint's active window: {exc}") from exc
    if window is None:
        raise BridgeError("PowerPoint has no open presentation window")

    selection = window.Selection
    if int(selection.Type) != _SELECTION_TYPE_SHAPES:
        raise BridgeError(
            "Select exactly one shape in PowerPoint before extracting "
            f"(selection type is {selection.Type}, not a shape selection)"
        )

    shape_range = selection.ShapeRange
    shape_count = int(shape_range.Count)
    slide_range = selection.SlideRange
    slide_count = int(slide_range.Count)
    if shape_count != 1 or slide_count != 1:
        raise BridgeError(
            "Select exactly one shape in PowerPoint before extracting "
            f"(got {shape_count} shape(s) on {slide_count} slide(s))"
        )

    presentation = window.Presentation
    if not bool(presentation.Saved):
        raise BridgeError(
            "The presentation has unsaved changes; save it in PowerPoint "
            "before extracting"
        )

    shape = shape_range.Item(1)
    slide = slide_range.Item(1)

    shape_type = int(shape.Type)
    shape_name = str(shape.Name)
    slide_index = int(slide.SlideIndex)
    presentation_path = str(presentation.FullName)

    if slide_index < 1:
        raise BridgeError(f"Unexpected PowerPoint slide index: {slide_index}")
    if not presentation_path:
        raise BridgeError("Unexpected empty PowerPoint presentation path")

    return SelectionInfo(
        shape_type=shape_type,
        shape_name=shape_name,
        slide_index=slide_index,
        presentation_path=presentation_path,
    )
