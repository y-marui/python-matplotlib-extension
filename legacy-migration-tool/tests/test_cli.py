from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
import pytest
from pypdf import PdfReader, PdfWriter

from legacy_migration_tool import cli
from legacy_migration_tool.confirm import CONFIRMATION_PHRASE


def _make_legacy_pdf(tmp_path: Path, name: str) -> Path:
    import dill

    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [2.0, 3.0])
    blob = dill.dumps(fig)
    plt.close(fig)

    rendered = BytesIO()
    fig2, ax2 = plt.subplots()
    ax2.plot([0.0, 1.0], [2.0, 3.0])
    fig2.savefig(rendered, format="pdf")
    plt.close(fig2)

    reader = PdfReader(BytesIO(rendered.getvalue()))
    writer = PdfWriter(clone_from=reader)
    writer.add_attachment("fig.dill", blob)
    legacy = tmp_path / name
    with legacy.open("wb") as stream:
        writer.write(stream)
    return legacy


def test_non_interactive_run_without_flag_refuses_and_converts_nothing(
    tmp_path: Path,
) -> None:
    legacy = _make_legacy_pdf(tmp_path, "legacy.plt.pdf")
    output_dir = tmp_path / "out"

    exit_code = cli.main(
        [str(legacy), "--output-dir", str(output_dir)],
    )

    assert exit_code == 1
    assert not output_dir.exists() or not list(output_dir.iterdir())


def test_allow_flag_converts_and_validates_multiple_inputs_with_one_confirmation(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    first = _make_legacy_pdf(tmp_path, "first.plt.pdf")
    second = _make_legacy_pdf(tmp_path, "second.plt.pdf")
    output_dir = tmp_path / "out"

    confirm_calls = []
    import legacy_migration_tool.confirm as confirm_module

    original_confirm_once = confirm_module.confirm_once

    def counting_confirm_once(**kwargs):
        confirm_calls.append(kwargs)
        return original_confirm_once(**kwargs)

    monkeypatch.setattr(cli, "confirm_once", counting_confirm_once)

    exit_code = cli.main(
        [
            str(first),
            str(second),
            "--output-dir",
            str(output_dir),
            "--allow-arbitrary-code-execution",
        ]
    )

    assert exit_code == 0
    assert len(confirm_calls) == 1
    assert confirm_calls[0]["allow_non_interactive"] is True
    assert sorted(p.name for p in output_dir.iterdir()) == [
        "first.mpl.png",
        "second.mpl.png",
    ]


def test_confirmation_phrase_constant_is_not_a_generic_yes() -> None:
    assert CONFIRMATION_PHRASE.lower() not in {"y", "yes", "ok"}
    assert len(CONFIRMATION_PHRASE) > 10


def test_abbreviated_allow_flag_is_rejected_not_silently_matched(
    tmp_path: Path,
) -> None:
    legacy = _make_legacy_pdf(tmp_path, "legacy.plt.pdf")
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit):
        cli.main(
            [str(legacy), "--output-dir", str(output_dir), "--allow"],
        )

    assert not output_dir.exists() or not list(output_dir.iterdir())


def test_a_save_failure_for_one_input_does_not_stop_the_batch(
    tmp_path: Path,
) -> None:
    first = _make_legacy_pdf(tmp_path, "first.plt.pdf")
    second = _make_legacy_pdf(tmp_path, "second.plt.pdf")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "first.mpl.png").write_bytes(b"pre-existing, blocks exclusive create")

    exit_code = cli.main(
        [
            str(first),
            str(second),
            "--output-dir",
            str(output_dir),
            "--allow-arbitrary-code-execution",
        ]
    )

    assert exit_code == 1
    assert (output_dir / "second.mpl.png").exists()
