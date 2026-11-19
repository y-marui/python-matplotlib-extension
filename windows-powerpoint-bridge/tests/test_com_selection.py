"""Tests for the selection-reading logic in
:mod:`windows_powerpoint_bridge.com_selection`.

These do not launch or talk to real PowerPoint; they check that
:func:`read_selection` interprets a given COM object graph the way this
module's docstrings claim, using plain fake objects standing in for the
COM wrappers ``win32com.client`` would normally return. The actual COM
property/method names (``Selection.Type``, ``ShapeRange``,
``SlideRange``, ``Shape.Type``/``Name``, ``Slide.SlideIndex``,
``Presentation.Saved``/``FullName``) have only been partially validated
against real PowerPoint for Windows -- see the handoff notes and this
module's own docstring for exactly what is confirmed vs. not.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from windows_powerpoint_bridge import com_selection
from windows_powerpoint_bridge.errors import BridgeError


@dataclass
class _FakeShape:
    Type: int
    Name: str


class _FakeRange:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    @property
    def Count(self) -> int:  # noqa: N802 -- mirrors the real COM property name
        return len(self._items)

    def Item(self, index: int) -> object:  # noqa: N802 -- mirrors the real COM method name
        return self._items[index - 1]


@dataclass
class _FakeSlide:
    SlideIndex: int


@dataclass
class _FakeSelection:
    Type: int
    ShapeRange: _FakeRange
    SlideRange: _FakeRange


@dataclass
class _FakePresentation:
    Saved: bool
    FullName: str


@dataclass
class _FakeWindow:
    Selection: _FakeSelection
    Presentation: _FakePresentation


@dataclass
class _FakeApplication:
    ActiveWindow: object


def _single_shape_window(
    *, shape_type: int, shape_name: str, slide_index: int, saved: bool, path: str
) -> _FakeWindow:
    selection = _FakeSelection(
        Type=com_selection._SELECTION_TYPE_SHAPES,
        ShapeRange=_FakeRange([_FakeShape(shape_type, shape_name)]),
        SlideRange=_FakeRange([_FakeSlide(slide_index)]),
    )
    return _FakeWindow(Selection=selection, Presentation=_FakePresentation(saved, path))


def test_reads_a_well_formed_single_selection() -> None:
    window = _single_shape_window(
        shape_type=7,
        shape_name="Figure 2",
        slide_index=2,
        saved=True,
        path=r"C:\Presentations\deck.pptx",
    )
    with patch.object(
        com_selection,
        "_get_running_application",
        return_value=_FakeApplication(window),
    ):
        info = com_selection.read_selection()
    assert info.shape_type == 7
    assert info.shape_name == "Figure 2"
    assert info.slide_index == 2
    assert info.presentation_path == r"C:\Presentations\deck.pptx"


def test_rejects_no_open_window() -> None:
    with patch.object(
        com_selection,
        "_get_running_application",
        return_value=_FakeApplication(None),
    ):
        with pytest.raises(BridgeError, match="no open presentation window"):
            com_selection.read_selection()


def test_rejects_non_shape_selection() -> None:
    selection = _FakeSelection(
        Type=3,  # ppSelectionText
        ShapeRange=_FakeRange([]),
        SlideRange=_FakeRange([]),
    )
    window = _FakeWindow(selection, _FakePresentation(True, r"C:\deck.pptx"))
    with patch.object(
        com_selection,
        "_get_running_application",
        return_value=_FakeApplication(window),
    ):
        with pytest.raises(BridgeError, match="Select exactly one shape"):
            com_selection.read_selection()


def test_rejects_multiple_selected_shapes() -> None:
    selection = _FakeSelection(
        Type=com_selection._SELECTION_TYPE_SHAPES,
        ShapeRange=_FakeRange([_FakeShape(7, "A"), _FakeShape(7, "B")]),
        SlideRange=_FakeRange([_FakeSlide(1)]),
    )
    window = _FakeWindow(selection, _FakePresentation(True, r"C:\deck.pptx"))
    with patch.object(
        com_selection,
        "_get_running_application",
        return_value=_FakeApplication(window),
    ):
        with pytest.raises(BridgeError, match="Select exactly one shape"):
            com_selection.read_selection()


def test_rejects_selection_spanning_multiple_slides() -> None:
    selection = _FakeSelection(
        Type=com_selection._SELECTION_TYPE_SHAPES,
        ShapeRange=_FakeRange([_FakeShape(7, "A")]),
        SlideRange=_FakeRange([_FakeSlide(1), _FakeSlide(2)]),
    )
    window = _FakeWindow(selection, _FakePresentation(True, r"C:\deck.pptx"))
    with patch.object(
        com_selection,
        "_get_running_application",
        return_value=_FakeApplication(window),
    ):
        with pytest.raises(BridgeError, match="Select exactly one shape"):
            com_selection.read_selection()


def test_rejects_unsaved_presentation() -> None:
    window = _single_shape_window(
        shape_type=7,
        shape_name="Figure 1",
        slide_index=1,
        saved=False,
        path=r"C:\deck.pptx",
    )
    with patch.object(
        com_selection,
        "_get_running_application",
        return_value=_FakeApplication(window),
    ):
        with pytest.raises(BridgeError, match="unsaved changes"):
            com_selection.read_selection()


def test_rejects_empty_presentation_path() -> None:
    window = _single_shape_window(
        shape_type=7, shape_name="Figure 1", slide_index=1, saved=True, path=""
    )
    with patch.object(
        com_selection,
        "_get_running_application",
        return_value=_FakeApplication(window),
    ):
        with pytest.raises(BridgeError, match="Unexpected empty"):
            com_selection.read_selection()


def test_wraps_application_connection_failure() -> None:
    def _raise() -> object:
        raise BridgeError(
            "Unable to connect to a running PowerPoint instance via COM: boom"
        )

    with patch.object(com_selection, "_get_running_application", side_effect=_raise):
        with pytest.raises(BridgeError, match="Unable to connect"):
            com_selection.read_selection()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="this checks the ImportError fallback that only matters where "
    "pywin32 is unavailable (i.e. not on Windows)",
)
def test_raises_a_clear_error_when_pywin32_is_unavailable() -> None:
    with pytest.raises(BridgeError, match="pywin32 is required"):
        com_selection.read_selection()
