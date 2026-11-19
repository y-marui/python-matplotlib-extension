#!/usr/bin/env python3
"""Regenerate the plain-generator pptx fixtures in this directory.

These are plain output of ``matplotlib_extension.pyplot.save_pptx()``,
never opened in PowerPoint -- the same role
``tests/fixtures/powerpoint_mac/generate_originals.py`` (issue #77)
plays for the macOS bridge. This script does **not** regenerate the
``*_powerpoint_resaved.pptx`` counterparts next to these files: those
require a real Windows PowerPoint resave, captured via a sibling
session with real Windows access rather than by this script (see
``README.md`` in this directory for exactly how and why).

Run this script (``uv run python
tests/fixtures/powerpoint_windows/generate_originals.py``) only when
deliberately changing what the fixtures contain.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import matplotlib  # noqa: E402

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from matplotlib_extension import pyplot as mplx  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent


def _figure(title: str, color: str) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(5, 3), dpi=100)
    ax.plot([0, 1, 2, 3], [0, 1, 4, 9], color=color)
    ax.set_title(title)
    return fig


def main() -> None:
    single = [_figure("Windows bridge fixture: single", "tab:blue")]
    mplx.save_pptx(single, OUT_DIR / "single_figure.pptx", mode="w")
    for fig in single:
        plt.close(fig)

    multi = [
        _figure("Windows bridge fixture: first", "tab:blue"),
        _figure("Windows bridge fixture: second", "tab:orange"),
        _figure("Windows bridge fixture: third", "tab:green"),
    ]
    mplx.save_pptx(multi, OUT_DIR / "multi_figure.pptx", mode="w")
    for fig in multi:
        plt.close(fig)

    print(f"Wrote single_figure.pptx and multi_figure.pptx to {OUT_DIR}")


if __name__ == "__main__":
    main()
