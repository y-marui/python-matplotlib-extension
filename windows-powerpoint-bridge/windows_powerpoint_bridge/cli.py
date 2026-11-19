"""Command-line entry point for the Windows PowerPoint extraction bridge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from matplotlib_extension.package import PackageError

from windows_powerpoint_bridge.bridge import extract_selected_figure
from windows_powerpoint_bridge.errors import BridgeError


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="windows-powerpoint-bridge",
        description=(
            "Extract the currently selected embedded OLE Figure object in "
            "PowerPoint for Windows to a figure.mpl.png file. "
            "Extraction-only: never restores a Figure, never runs embedded "
            "code, never uploads the presentation."
        ),
    )
    parser.add_argument(
        "destination",
        type=Path,
        help="Destination path, ending in .mpl.png.",
    )
    parser.add_argument(
        "--mode",
        choices=("x", "w"),
        default="x",
        help="'x' (default) for exclusive creation, 'w' for atomic overwrite.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        destination = extract_selected_figure(args.destination, mode=args.mode)
    except (BridgeError, PackageError) as exc:
        print(f"windows-powerpoint-bridge: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
