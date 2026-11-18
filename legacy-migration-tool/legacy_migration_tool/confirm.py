"""Informed-consent gate for legacy deserialization.

This module never imports ``dill``. It only decides whether the caller may
proceed to :mod:`legacy_migration_tool.convert`, which performs the actual
deserialization. The gate runs once per process invocation, before any
input file is converted, regardless of how many files were declared.
"""

from __future__ import annotations

import sys
from typing import TextIO

CONFIRMATION_PHRASE = "I accept the arbitrary code execution risk"

_WARNING = f"""
WARNING: this file may contain an arbitrary Python object stream (dill).
Converting it EXECUTES ARBITRARY CODE embedded in the file, with the same
privileges as this process.

Typing the confirmation phrase below and the separate process this tool
runs in are informed consent, not a security boundary. Convert only files
you trust, and do so in a disposable environment with networking
disabled, the input mounted read-only, and write access limited to one
dedicated output directory. See this tool's README for details.

Type exactly the phrase below and press Enter to continue:
  {CONFIRMATION_PHRASE}
"""

_AUTOMATION_NOTICE = (
    "Proceeding non-interactively because --allow-arbitrary-code-execution "
    "was given. That flag does not make dill safe: it only records that "
    "the operator accepted the risk out-of-band, outside this prompt.\n"
)

_REFUSAL_MESSAGE = (
    "Refusing to run without a terminal to confirm in. This tool never "
    "deserializes a legacy file without either an interactive confirmation "
    "or the explicit --allow-arbitrary-code-execution flag (see README)."
)


class ConfirmationError(RuntimeError):
    """Raised when the operator does not grant explicit confirmation."""


class NonInteractiveRefusalError(ConfirmationError):
    """Raised when run without a TTY and without the automation flag."""


def confirm_once(
    *,
    allow_non_interactive: bool,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> None:
    """Gate one tool invocation before any legacy deserialization.

    Call this exactly once per process, before converting any input file.

    Args:
        allow_non_interactive: Set only by the deliberately-named
            ``--allow-arbitrary-code-execution`` CLI flag, never by a
            generic ``--yes``.
        stdin: Input stream to read the confirmation phrase from.
            Defaults to ``sys.stdin``; overridable for tests.
        stdout: Stream the warning and notices are written to. Defaults
            to ``sys.stdout``; overridable for tests.

    Raises:
        NonInteractiveRefusalError: No TTY and ``allow_non_interactive``
            is false.
        ConfirmationError: A TTY is present but the typed phrase does not
            match exactly.
    """
    in_stream: TextIO = sys.stdin if stdin is None else stdin
    out_stream: TextIO = sys.stdout if stdout is None else stdout

    if allow_non_interactive:
        out_stream.write(_AUTOMATION_NOTICE)
        return

    if not in_stream.isatty():
        raise NonInteractiveRefusalError(_REFUSAL_MESSAGE)

    out_stream.write(_WARNING)
    response = in_stream.readline().rstrip("\r\n")
    if response != CONFIRMATION_PHRASE:
        raise ConfirmationError(
            "Confirmation phrase did not match exactly; aborting without "
            "converting anything."
        )
