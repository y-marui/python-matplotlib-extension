import io

import pytest

from legacy_migration_tool.confirm import (
    CONFIRMATION_PHRASE,
    ConfirmationError,
    ConversionConsent,
    NonInteractiveRefusalError,
    confirm_once,
)


class _FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


class _FakeNonTTY(io.StringIO):
    def isatty(self) -> bool:
        return False


class _RecordingTTY(_FakeTTY):
    def __init__(self, text: str, log: list[str]) -> None:
        super().__init__(text)
        self._log = log

    def readline(self, *args: object, **kwargs: object) -> str:
        self._log.append("readline")
        return super().readline(*args, **kwargs)  # type: ignore[arg-type]


class _RecordingStdout(io.StringIO):
    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self._log = log

    def flush(self) -> None:
        self._log.append("flush")
        super().flush()


def test_correct_phrase_on_a_tty_proceeds() -> None:
    stdin = _FakeTTY(CONFIRMATION_PHRASE + "\n")
    stdout = io.StringIO()
    consent = confirm_once(allow_non_interactive=False, stdin=stdin, stdout=stdout)
    assert "WARNING" in stdout.getvalue()
    assert isinstance(consent, ConversionConsent)


def test_warning_is_flushed_before_reading_the_confirmation() -> None:
    log: list[str] = []
    stdin = _RecordingTTY(CONFIRMATION_PHRASE + "\n", log)
    stdout = _RecordingStdout(log)

    confirm_once(allow_non_interactive=False, stdin=stdin, stdout=stdout)

    assert log.index("flush") < log.index("readline")


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
    consent = confirm_once(allow_non_interactive=True, stdin=stdin, stdout=stdout)
    assert "out-of-band" in stdout.getvalue()
    assert isinstance(consent, ConversionConsent)


def test_flag_also_bypasses_the_prompt_on_a_tty() -> None:
    stdin = _FakeTTY("")
    stdout = io.StringIO()
    consent = confirm_once(allow_non_interactive=True, stdin=stdin, stdout=stdout)
    assert "out-of-band" in stdout.getvalue()
    assert isinstance(consent, ConversionConsent)
