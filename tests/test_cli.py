from collections.abc import Callable

import pytest

from jarvis.cli import ask_confirmation


def scripted(*answers: str) -> Callable[[str], str]:
    remaining = list(answers)
    return lambda _prompt: remaining.pop(0)


@pytest.mark.parametrize("answer", ["s", "S", "sí", " si "])
def test_confirmation_accepts_yes(answer: str) -> None:
    assert ask_confirmation("¿Enviar?", read=scripted(answer)) is True


def test_confirmation_rejects_no() -> None:
    assert ask_confirmation("¿Enviar?", read=scripted("n")) is False


def test_confirmation_asks_again_on_invalid_answer() -> None:
    assert ask_confirmation("¿Enviar?", read=scripted("quizás", "s")) is True


def test_confirmation_end_of_input_means_no() -> None:
    def eof(_prompt: str) -> str:
        raise EOFError

    assert ask_confirmation("¿Enviar?", read=eof) is False
