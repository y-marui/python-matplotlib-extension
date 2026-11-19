"""Tests for the response-parsing logic in :mod:`macos_powerpoint_bridge.applescript`.

These do not launch or talk to real PowerPoint; they only check that
:func:`read_selection` interprets a given raw ``osascript`` response the
way this module's docstrings claim. The actual AppleScript text was
validated by hand against real PowerPoint for Mac 16.112.4 (see the
PR description / handoff notes); it is not re-verified here.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from macos_powerpoint_bridge import applescript
from macos_powerpoint_bridge.errors import BridgeError

_SEP = applescript._FIELD_SEPARATOR


def _line(
    *,
    shape_count: str = "1",
    slide_count: str = "1",
    shape_type: str = "shape type embedded OLE control",
    slide_index: str = "1",
    saved: str = "true",
    shape_name: str = "Figure 1",
    presentation_path: str = "/tmp/deck.pptx",
) -> str:
    fields = {
        "shapeCount": shape_count,
        "slideCount": slide_count,
        "shapeType": shape_type,
        "slideIndex": slide_index,
        "saved": saved,
        "shapeName": shape_name,
        "presentationPath": presentation_path,
    }
    return _SEP.join(f"{name}={fields[name]}" for name in applescript._FIELD_NAMES)


def test_reads_a_well_formed_single_selection() -> None:
    line = _line(
        slide_index="2",
        shape_name="Figure 2",
        presentation_path="/tmp/deck.pptx",
    )
    with patch.object(applescript, "_run_osascript", return_value=line):
        info = applescript.read_selection()
    assert info.shape_type == "shape type embedded OLE control"
    assert info.shape_name == "Figure 2"
    assert info.slide_index == 2
    assert info.presentation_path == "/tmp/deck.pptx"


def test_reads_the_selection_in_exactly_one_osascript_call() -> None:
    """Combining fields into one call closes the TOCTOU gap between
    validating the selection and reading its shape name/path."""
    with patch.object(applescript, "_run_osascript", return_value=_line()) as mock_run:
        applescript.read_selection()
    assert mock_run.call_count == 1


def test_rejects_no_selection() -> None:
    line = _line(
        shape_count="0",
        slide_count="0",
        shape_type="",
        slide_index="0",
        saved="false",
        shape_name="",
        presentation_path="",
    )
    with patch.object(applescript, "_run_osascript", return_value=line):
        with pytest.raises(BridgeError, match="Select exactly one shape"):
            applescript.read_selection()


def test_rejects_multiple_selected_shapes() -> None:
    line = _line(
        shape_count="2",
        shape_type="",
        slide_index="0",
        saved="false",
        shape_name="",
        presentation_path="",
    )
    with patch.object(applescript, "_run_osascript", return_value=line):
        with pytest.raises(BridgeError, match="Select exactly one shape"):
            applescript.read_selection()


def test_rejects_unsaved_presentation() -> None:
    line = _line(saved="false")
    with patch.object(applescript, "_run_osascript", return_value=line):
        with pytest.raises(BridgeError, match="unsaved changes"):
            applescript.read_selection()


def test_rejects_zero_slide_index() -> None:
    line = _line(slide_index="0")
    with patch.object(applescript, "_run_osascript", return_value=line):
        with pytest.raises(BridgeError, match="Unexpected PowerPoint slide index"):
            applescript.read_selection()


@pytest.mark.parametrize(
    "malformed",
    [
        f"shapeCount=1{_SEP}slideCount=1{_SEP}shapeType=x{_SEP}slideIndex=1",  # missing
        "shapeCount=1;slideCount=1;shapeType=x;slideIndex=1;saved=true",  # wrong sep
        f"slideCount=1{_SEP}shapeCount=1{_SEP}shapeType=x{_SEP}slideIndex=1"
        f"{_SEP}saved=true{_SEP}shapeName=a{_SEP}presentationPath=/b",  # wrong order
    ],
)
def test_rejects_malformed_responses(malformed: str) -> None:
    with patch.object(applescript, "_run_osascript", return_value=malformed):
        with pytest.raises(BridgeError, match="Unexpected PowerPoint"):
            applescript.read_selection()


def test_rejects_non_absolute_presentation_path() -> None:
    line = _line(presentation_path="relative/path.pptx")
    with patch.object(applescript, "_run_osascript", return_value=line):
        with pytest.raises(
            BridgeError, match="Unexpected PowerPoint presentation path"
        ):
            applescript.read_selection()


def test_shape_name_may_contain_the_field_name_delimiter() -> None:
    """A shape name containing "=" must not confuse field parsing, since
    only the first "=" in each field separates its name from its value."""
    line = _line(shape_name="Figure = 1")
    with patch.object(applescript, "_run_osascript", return_value=line):
        info = applescript.read_selection()
    assert info.shape_name == "Figure = 1"
