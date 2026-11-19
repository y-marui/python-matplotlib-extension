"""Read-only AppleScript queries against PowerPoint for Mac's live selection.

Every script here only reads state: the current selection, the shape and
slide it resolves to, and the owning presentation's saved status and
path. None of them call PowerPoint's generic ``save`` command on the
user's live, already-open document.

An empirical pass against real PowerPoint for Mac (16.112.4) found that
``save <presentation> in <file> as <format>`` behaves like interactive
File > Save As: it rebinds the open document window to the new file,
changing its name and path. That is exactly the kind of live-document
mutation this extraction-only bridge must never perform. Instead,
:func:`read_selection` requires the presentation to already be fully
saved (``saved of presentation`` is true) and returns its path; the
caller takes its own read-only filesystem copy of that path rather than
asking PowerPoint to export one. See docs/EDITABLE_FORMAT.md's
"OLE Boundary" section.

The same pass found that ``select <shape>`` only changes
``selection of document window 1`` once the window's own current slide
(``slide of (view of document window 1)``) already shows that shape;
selecting a shape without first navigating the view to its slide
silently leaves the selection unchanged (``selection type: none``). This
module only reads the selection the user (or another script) already
made; it never drives the view or calls ``select`` itself.

Every field -- including the shape name and presentation path, which
are otherwise arbitrary text -- is read in a single ``osascript``
invocation, joined by the ASCII Unit Separator (0x1F). A single call
avoids the TOCTOU gap of querying the live selection and presentation
across several separate round trips (the user could change the
selection, or PowerPoint's own AutoSave could write new content,
between calls) and the latency of launching the AppleScript runtime
more than once per extraction. 0x1F is chosen specifically because a
real shape name or filesystem path essentially never contains it; if
one somehow did, the field count below would no longer match and
:func:`read_selection` fails closed rather than silently misparsing.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from macos_powerpoint_bridge.errors import BridgeError

ALLOWED_SHAPE_TYPE = "shape type embedded OLE control"

_OSASCRIPT = "/usr/bin/osascript"
_TIMEOUT_SECONDS = 30
_FIELD_SEPARATOR = "\x1f"

_FIELD_NAMES = (
    "shapeCount",
    "slideCount",
    "shapeType",
    "slideIndex",
    "saved",
    "shapeName",
    "presentationPath",
)

# Every branch returns the same seven "name=value" fields, joined by
# _FIELD_SEPARATOR, so a missing-selection or wrong-count response is still
# a well-formed line this module's parser recognizes (and then rejects on
# the field values) rather than a shape this script has to special-case.
_SELECTION_SCRIPT = """
tell application "Microsoft PowerPoint"
    set sep to (ASCII character 31)
    if (count of document windows) is 0 then
        set resultText to "shapeCount=0" & sep & "slideCount=0"
        set resultText to resultText & sep & "shapeType=" & sep & "slideIndex=0"
        set resultText to resultText & sep & "saved=false" & sep & "shapeName="
        set resultText to resultText & sep & "presentationPath="
        return resultText
    end if
    set win to document window 1
    set sel to selection of win
    set shapeRange to shape range of sel
    set shapeCount to count of shapes of shapeRange
    set slideRange to slide range of sel
    set slideCount to count of slides of slideRange
    if shapeCount is not 1 or slideCount is not 1 then
        set resultText to "shapeCount=" & shapeCount
        set resultText to resultText & sep & "slideCount=" & slideCount
        set resultText to resultText & sep & "shapeType=" & sep & "slideIndex=0"
        set resultText to resultText & sep & "saved=false" & sep & "shapeName="
        set resultText to resultText & sep & "presentationPath="
        return resultText
    end if
    set theShape to shape 1 of shapeRange
    set theSlide to slide 1 of slideRange
    set thePresentation to presentation of win
    set shapeTypeText to (shape type of theShape) as text
    set slideIdx to slide index of theSlide
    set isSaved to saved of thePresentation
    set shapeNameText to name of theShape
    set presentationPathText to full name of thePresentation
    set resultText to "shapeCount=" & shapeCount
    set resultText to resultText & sep & "slideCount=" & slideCount
    set resultText to resultText & sep & "shapeType=" & shapeTypeText
    set resultText to resultText & sep & "slideIndex=" & slideIdx
    set resultText to resultText & sep & "saved=" & isSaved
    set resultText to resultText & sep & "shapeName=" & shapeNameText
    set resultText to resultText & sep & "presentationPath=" & presentationPathText
    return resultText
end tell
"""


@dataclass(frozen=True)
class SelectionInfo:
    """The exactly-one selected shape, and its exactly-one slide."""

    shape_type: str
    shape_name: str
    slide_index: int
    presentation_path: str


def _run_osascript(script: str) -> str:
    try:
        result = subprocess.run(
            [_OSASCRIPT, "-e", script],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except OSError as exc:
        raise BridgeError(f"Unable to run osascript: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BridgeError("osascript did not respond in time") from exc
    except UnicodeDecodeError as exc:
        raise BridgeError(
            f"Unable to decode PowerPoint's AppleScript response: {exc}"
        ) from exc
    if result.returncode != 0:
        raise BridgeError(
            "PowerPoint AppleScript query failed: " + result.stderr.strip()
        )
    return result.stdout.rstrip("\n")


def _parse_selection_fields(line: str) -> dict[str, str]:
    parts = line.split(_FIELD_SEPARATOR)
    if len(parts) != len(_FIELD_NAMES):
        raise BridgeError(f"Unexpected PowerPoint selection response: {line!r}")
    fields: dict[str, str] = {}
    for part, expected_name in zip(parts, _FIELD_NAMES, strict=True):
        name, separator, value = part.partition("=")
        if separator != "=" or name != expected_name:
            raise BridgeError(f"Unexpected PowerPoint selection response: {line!r}")
        fields[name] = value
    return fields


def read_selection() -> SelectionInfo:
    """Read the current PowerPoint-for-Mac selection, read-only.

    Raises:
        BridgeError: If PowerPoint cannot be queried, the selection is not
            exactly one shape on exactly one slide, the presentation has
            unsaved changes, or PowerPoint's response is not in the exact
            shape this parser expects.
    """
    fields = _parse_selection_fields(_run_osascript(_SELECTION_SCRIPT))
    if fields["shapeCount"] != "1" or fields["slideCount"] != "1":
        raise BridgeError(
            "Select exactly one shape in PowerPoint before extracting "
            f"(got {fields['shapeCount']} shape(s) on "
            f"{fields['slideCount']} slide(s))"
        )
    if fields["saved"] != "true":
        raise BridgeError(
            "The presentation has unsaved changes; save it in PowerPoint "
            "before extracting"
        )
    try:
        slide_index = int(fields["slideIndex"])
    except ValueError as exc:
        raise BridgeError(
            f"Unexpected PowerPoint slide index: {fields['slideIndex']!r}"
        ) from exc
    if slide_index < 1:
        raise BridgeError(f"Unexpected PowerPoint slide index: {slide_index}")

    presentation_path = fields["presentationPath"]
    if not presentation_path.startswith("/"):
        raise BridgeError(
            f"Unexpected PowerPoint presentation path: {presentation_path!r}"
        )
    return SelectionInfo(
        shape_type=fields["shapeType"],
        shape_name=fields["shapeName"],
        slide_index=slide_index,
        presentation_path=presentation_path,
    )
