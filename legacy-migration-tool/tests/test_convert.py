import ast
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib_extension
import numpy as np
import pytest
from pypdf import PdfReader, PdfWriter

from legacy_migration_tool.confirm import confirm_once
from legacy_migration_tool.convert import LegacyConversionError, convert_file


def _consent():
    return confirm_once(allow_non_interactive=True)


def _render_base_pdf() -> bytes:
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [2.0, 3.0])
    rendered = BytesIO()
    fig.savefig(rendered, format="pdf")
    plt.close(fig)
    return rendered.getvalue()


def _make_legacy_pdf(tmp_path: Path, *, attachment_name: str = "fig.dill") -> Path:
    import dill

    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [2.0, 3.0])
    blob = dill.dumps(fig)
    plt.close(fig)

    reader = PdfReader(BytesIO(_render_base_pdf()))
    writer = PdfWriter(clone_from=reader)
    writer.add_attachment(attachment_name, blob)
    legacy = tmp_path / "legacy.plt.pdf"
    with legacy.open("wb") as stream:
        writer.write(stream)
    return legacy


def test_convert_file_round_trips_through_plain_loadfig(tmp_path: Path) -> None:
    legacy = _make_legacy_pdf(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    output_path = convert_file(legacy, output_dir, _consent())

    assert output_path.name == "legacy.mpl.png"
    restored = matplotlib_extension.loadfig(output_path)
    line = restored.axes[0].lines[0]
    np.testing.assert_allclose(line.get_xdata(), [0.0, 1.0])
    np.testing.assert_allclose(line.get_ydata(), [2.0, 3.0])
    plt.close(restored)


def test_convert_file_rejects_input_without_the_legacy_attachment(
    tmp_path: Path,
) -> None:
    plain = tmp_path / "plain.plt.pdf"
    plain.write_bytes(_render_base_pdf())
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(LegacyConversionError, match="no 'fig.dill' attachment"):
        convert_file(plain, output_dir, _consent())


def test_convert_file_rejects_non_figure_object_streams(tmp_path: Path) -> None:
    legacy = _make_legacy_pdf(tmp_path)
    reader = PdfReader(legacy)
    assert reader.attachments["fig.dill"]

    # A stream that deserializes but is not a Figure must still be rejected.
    import dill

    not_a_figure = tmp_path / "not_a_figure.plt.pdf"
    writer = PdfWriter(clone_from=PdfReader(BytesIO(_render_base_pdf())))
    writer.add_attachment("fig.dill", dill.dumps({"not": "a figure"}))
    with not_a_figure.open("wb") as stream:
        writer.write(stream)

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    with pytest.raises(LegacyConversionError, match="not a Matplotlib Figure"):
        convert_file(not_a_figure, output_dir, _consent())


def test_convert_file_refuses_without_confirmation_before_touching_the_file(
    tmp_path: Path,
) -> None:
    nonexistent = tmp_path / "does-not-exist.plt.pdf"
    output_dir = tmp_path / "out"

    with pytest.raises(LegacyConversionError, match="without confirmation"):
        convert_file(nonexistent, output_dir, None)  # type: ignore[arg-type]


def test_convert_file_wraps_a_save_failure_as_legacy_conversion_error(
    tmp_path: Path,
) -> None:
    legacy = _make_legacy_pdf(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "legacy.mpl.png").write_bytes(b"pre-existing output file")

    with pytest.raises(LegacyConversionError, match="failed to save"):
        convert_file(legacy, output_dir, _consent())


def test_only_convert_module_imports_dill() -> None:
    package_dir = Path(__file__).resolve().parents[1] / "legacy_migration_tool"
    importers = []
    for path in sorted(package_dir.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == "dill" for alias in node.names
            ):
                importers.append(path.name)
            if isinstance(node, ast.ImportFrom) and node.module == "dill":
                importers.append(path.name)
    assert importers == ["convert.py"]


def test_importing_cli_and_confirm_never_imports_dill() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "from legacy_migration_tool import cli, confirm\n"
            "print('dill' in sys.modules)\n",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"


def test_matplotlib_extension_never_imports_dill() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys\nimport matplotlib_extension\nprint('dill' in sys.modules)\n",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"
