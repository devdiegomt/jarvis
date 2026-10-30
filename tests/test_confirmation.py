import pytest

from jarvis.confirmation import parse_yes_no


@pytest.mark.parametrize("answer", ["s", "S", "sí", "Si", " si. ", "yes", "¡Sí!", "Sí,"])
def test_yes(answer: str) -> None:
    assert parse_yes_no(answer) is True


@pytest.mark.parametrize("answer", ["n", "NO", "no!", "No.", "¿no?"])
def test_no(answer: str) -> None:
    assert parse_yes_no(answer) is False


@pytest.mark.parametrize("answer", ["", "quizás", "sí, pero luego"])
def test_invalid(answer: str) -> None:
    assert parse_yes_no(answer) is None
