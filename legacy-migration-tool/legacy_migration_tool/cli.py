"""Command-line entry point for the deprecated legacy migration tool.

Deliberately deprecated and migration-only: this exposes exactly one
operation (convert legacy ``.plt.pdf`` files to safe ``.mpl.png`` files)
and must not grow editing, viewing, or other day-to-day features. See
README.md for the full security model.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from legacy_migration_tool.confirm import ConfirmationError, confirm_once
from legacy_migration_tool.convert import LegacyConversionError, convert_file


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="legacy-migration-tool",
        description=(
            "Deprecated, isolated one-way converter from legacy "
            "dill-based .plt.pdf figures to safe .mpl.png files. "
            "This executes arbitrary code embedded in each input file; "
            "read README.md before running it."
        ),
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="One or more legacy .plt.pdf files to convert.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help=(
            "Single dedicated directory to write .mpl.png files into. "
            "Should be the only path this process has write access to."
        ),
    )
    parser.add_argument(
        "--allow-arbitrary-code-execution",
        action="store_true",
        help=(
            "Skip the interactive confirmation prompt for non-interactive "
            "automation. This does NOT make dill safe; it only records "
            "that the operator accepted the risk out-of-band. Only use "
            "this after reading README.md."
        ),
    )
    return parser.parse_args(argv)


def run_validation(output_path: Path) -> None:
    """Validate one converted file in a fresh, non-legacy subprocess."""
    result = subprocess.run(
        [sys.executable, "-m", "legacy_migration_tool.validate", str(output_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise LegacyConversionError(
            f"{output_path}: failed post-conversion validation via "
            f"loadfig() in a fresh process: {result.stderr.strip()}"
        )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        confirm_once(allow_non_interactive=args.allow_arbitrary_code_execution)
    except ConfirmationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)

    failures = 0
    for input_path in args.inputs:
        try:
            output_path = convert_file(input_path, args.output_dir)
            run_validation(output_path)
        except LegacyConversionError as exc:
            print(str(exc), file=sys.stderr)
            failures += 1
            continue
        print(f"{input_path} -> {output_path} (validated)")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
