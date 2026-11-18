import io

import pytest

from legacy_migration_tool.confirm import (
    CONFIRMATION_PHRASE,
    ConfirmationError,
    NonInteractiveRefusalError,
    confirm_once,
)


class _FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


class _FakeNonTTY(io.StringIO):
    def isatty(self) -> bool:
        return False


def test_correct_phrase_on_a_tty_proceeds() -> None:
    stdin = _FakeTTY(CONFIRMATION_PHRASE + "\n")
    stdout = io.StringIO()
    confirm_once(allow_non_interactive=False, stdin=stdin, stdout=stdout)
    assert "WARNING" in stdout.getvalue()


def test_wrong_phrase_on_a_tty_raises_confirmation_error() -> None:
    stdin = _FakeTTY("yes\n")
    stdout = io.StringIO()
    with pytest.raises(ConfirmationError):
        confirm_once(allow_non_interactive=False, stdin=stdin, stdout=stdout)


def test_generic_yes_is_not_an_accepted_phrase() -> None:
    stdin = _FakeTTY("y\n")
    stdout = io.StringIO()
    with pytest.raises(ConfirmationError):
        confirm_once(allow_non_interactive=False, stdin=stdin, stdout=stdout)


def test_non_interactive_without_flag_is_refused() -> None:
    stdin = _FakeNonTTY("")
    stdout = io.StringIO()
    with pytest.raises(NonInteractiveRefusalError):
        confirm_once(allow_non_interactive=False, stdin=stdin, stdout=stdout)
    assert stdout.getvalue() == ""


def test_non_interactive_with_flag_bypasses_the_prompt() -> None:
    stdin = _FakeNonTTY("")
    stdout = io.StringIO()
    confirm_once(allow_non_interactive=True, stdin=stdin, stdout=stdout)
    assert "out-of-band" in stdout.getvalue()


def test_flag_also_bypasses_the_prompt_on_a_tty() -> None:
    stdin = _FakeTTY("")
    stdout = io.StringIO()
    confirm_once(allow_non_interactive=True, stdin=stdin, stdout=stdout)
    assert "out-of-band" in stdout.getvalue()
