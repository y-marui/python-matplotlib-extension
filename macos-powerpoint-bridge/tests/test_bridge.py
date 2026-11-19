from pathlib import Path
from unittest.mock import patch

import matplotlib.pyplot as plt
import pytest
from matplotlib_extension.pyplot import loadfig

from macos_powerpoint_bridge.applescript import SelectionInfo
from macos_powerpoint_bridge.bridge import extract_selected_figure
from macos_powerpoint_bridge.errors import BridgeError

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "powerpoint_mac"


def _selection(
    presentation: str, *, slide_index: int, shape_name: str, shape_type: str
) -> SelectionInfo:
    return SelectionInfo(
        shape_type=shape_type,
        shape_name=shape_name,
        slide_index=slide_index,
        presentation_path=str(FIXTURES / presentation),
    )


def test_extracts_the_selected_figure_end_to_end(tmp_path: Path) -> None:
    selection = _selection(
        "multi_figure_powerpoint_resaved.pptx",
        slide_index=2,
        shape_name="Figure 2",
        shape_type="shape type embedded OLE control",
    )
    destination = tmp_path / "out.mpl.png"
    with patch("macos_powerpoint_bridge.bridge.read_selection", return_value=selection):
        result = extract_selected_figure(destination)

    assert result == destination
    figure = loadfig(destination)
    assert figure.axes[0].get_title() == "macOS bridge fixture: second"
    plt.close(figure)


def test_rejects_a_non_ole_shape_type(tmp_path: Path) -> None:
    selection = _selection(
        "single_figure.pptx",
        slide_index=1,
        shape_name="Figure 1",
        shape_type="shape type text box",
    )
    with patch("macos_powerpoint_bridge.bridge.read_selection", return_value=selection):
        with pytest.raises(BridgeError, match="not an embedded OLE object"):
            extract_selected_figure(tmp_path / "out.mpl.png")


def test_exclusive_mode_refuses_to_overwrite(tmp_path: Path) -> None:
    selection = _selection(
        "single_figure.pptx",
        slide_index=1,
        shape_name="Figure 1",
        shape_type="shape type embedded OLE control",
    )
    destination = tmp_path / "out.mpl.png"
    destination.write_bytes(b"already exists")
    with patch("macos_powerpoint_bridge.bridge.read_selection", return_value=selection):
        with pytest.raises(FileExistsError):
            extract_selected_figure(destination, mode="x")


def test_leaves_no_temp_file_behind_on_success(tmp_path: Path) -> None:
    selection = _selection(
        "single_figure.pptx",
        slide_index=1,
        shape_name="Figure 1",
        shape_type="shape type embedded OLE control",
    )
    destination = tmp_path / "out.mpl.png"
    with patch("macos_powerpoint_bridge.bridge.read_selection", return_value=selection):
        extract_selected_figure(destination)
    assert list(tmp_path.iterdir()) == [destination]


def test_leaves_no_temp_file_behind_on_failure(tmp_path: Path) -> None:
    selection = _selection(
        "single_figure.pptx",
        slide_index=1,
        shape_name="wrong name",
        shape_type="shape type embedded OLE control",
    )
    destination = tmp_path / "out.mpl.png"
    with patch("macos_powerpoint_bridge.bridge.read_selection", return_value=selection):
        with pytest.raises(BridgeError):
            extract_selected_figure(destination)
    assert list(tmp_path.iterdir()) == []
