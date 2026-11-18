"""Validate a converted ``.mpl.png`` through the normal safe reader.

This module never imports ``dill`` or anything from
:mod:`legacy_migration_tool.convert`. It only calls
``matplotlib_extension.loadfig``, the same ordinary, non-legacy code path
any other caller uses. :func:`legacy_migration_tool.cli.run_validation`
invokes this as ``python -m legacy_migration_tool.validate <path>`` in a
fresh subprocess, so the check happens outside the process that performed
the legacy deserialization.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib_extension


def validate(path: Path) -> None:
    """Load ``path`` with the normal safe reader, raising on failure."""
    fig = matplotlib_extension.loadfig(path)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m legacy_migration_tool.validate <path>", file=sys.stderr)
        return 2
    try:
        validate(Path(args[0]))
    except Exception as exc:
        print(f"validation failed for {args[0]}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
