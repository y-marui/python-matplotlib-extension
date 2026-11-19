from pathlib import Path
from unittest.mock import patch

import pytest

from macos_powerpoint_bridge.applescript import SelectionInfo
from macos_powerpoint_bridge.cli import main

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "powerpoint_mac"


def _selection() -> SelectionInfo:
    return SelectionInfo(
        shape_type="shape type embedded OLE control",
        shape_name="Figure 1",
        slide_index=1,
        presentation_path=str(FIXTURES / "single_figure.pptx"),
    )


def test_main_reports_a_clean_error_instead_of_a_traceback_on_existing_destination(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "out.mpl.png"
    destination.write_bytes(b"already exists")
    with patch(
        "macos_powerpoint_bridge.bridge.read_selection", return_value=_selection()
    ):
        exit_code = main([str(destination)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "macos-powerpoint-bridge:" in captured.err


def test_main_reports_a_clean_error_for_a_missing_destination_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "no-such-directory" / "out.mpl.png"
    with patch(
        "macos_powerpoint_bridge.bridge.read_selection", return_value=_selection()
    ):
        exit_code = main([str(destination)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "macos-powerpoint-bridge:" in captured.err


def test_main_succeeds_and_prints_the_destination(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "out.mpl.png"
    with patch(
        "macos_powerpoint_bridge.bridge.read_selection", return_value=_selection()
    ):
        exit_code = main([str(destination)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert str(destination) in captured.out
