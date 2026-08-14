"""Casamento da frase de ativação sobre texto transcrito."""

import pytest

from jarvis.voice.errors import InvalidVoiceInputError
from jarvis.voice.wake import WakePhrase, edit_distance, matches, normalize, parse_phrases


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Jarvis", "jarvis"),
        ("JÁRVIS,", "jarvis"),
        ("  jarvis!  que horas são?  ", "jarvis que horas sao"),
        ("Jarvis — apague o arquivo.", "jarvis apague o arquivo"),
        ("...", ""),
    ],
)
def test_normalize_strips_case_accent_and_punctuation(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [("jarvis", "jarvis", 0), ("jarvis", "jarves", 1), ("jarvis", "harves", 2), ("a", "abc", 2)],
)
def test_edit_distance_counts_edits(left: str, right: str, expected: int) -> None:
    assert edit_distance(left, right, cap=5) == expected


def test_edit_distance_gives_up_past_the_cap() -> None:
    # O corte é o que mantém a função barata quando ela roda por token, por
    # segmento, no modo de wake word por transcrição.
    assert edit_distance("jarvis", "computador", cap=1) == 2


def test_exact_phrase_activates_and_returns_the_rest() -> None:
    found = matches("Jarvis, que horas são?", [WakePhrase(text="jarvis")])

    assert found == ("jarvis", "que horas sao")


def test_a_single_typo_still_activates() -> None:
    # Transcritores devolvem "jarves"/"jarvez" com frequência suficiente para que
    # exigir exatidão fosse o mesmo que não ter wake word.
    assert matches("jarves apague o arquivo", [WakePhrase(text="jarvis")]) is not None


def test_two_typos_do_not_activate() -> None:
    assert matches("harves apague o arquivo", [WakePhrase(text="jarvis")]) is None


def test_a_word_in_the_middle_of_the_sentence_does_not_activate() -> None:
    # É a regra que impede que uma TV ligada vire comando.
    assert matches("o jarvis do filme apaga tudo", [WakePhrase(text="jarvis")]) is None


def test_any_word_before_the_phrase_blocks_activation() -> None:
    # Tolerar uma palavra qualquer antes do nome reabriria o buraco do teste
    # acima, cujo contraexemplo começa com "o". Quem quer "ei jarvis" registra a
    # frase inteira em JARVIS_WAKE_PHRASES.
    assert matches("ó jarvis, bom dia", [WakePhrase(text="jarvis")]) is None
    assert matches("ó jarvis, bom dia", [WakePhrase(text="o jarvis")]) == ("o jarvis", "bom dia")


def test_a_multiword_phrase_matches_in_order() -> None:
    phrase = WakePhrase(text="ei jarvis")

    assert matches("ei jarvis toca musica", [phrase]) == ("ei jarvis", "toca musica")
    assert matches("jarvis ei toca musica", [phrase]) is None


def test_fuzzy_matching_never_applies_to_short_tokens() -> None:
    # Distância 1 sobre "ei" casaria com metade do dicionário.
    assert matches("ai jarvis", [WakePhrase(text="ei jarvis")]) is None


def test_wake_only_activates_when_something_was_said() -> None:
    assert matches("", [WakePhrase(text="jarvis")]) is None
    assert matches("...", [WakePhrase(text="jarvis")]) is None


def test_activation_without_a_command_returns_an_empty_remainder() -> None:
    assert matches("jarvis", [WakePhrase(text="jarvis")]) == ("jarvis", "")


def test_alternative_phrases_are_tried_in_order() -> None:
    phrases = (WakePhrase(text="jarvis"), WakePhrase(text="computador"))

    assert matches("computador, ligue a luz", phrases) == ("computador", "ligue a luz")


def test_phrases_are_normalized_on_construction() -> None:
    assert WakePhrase(text=" Járvis! ").text == "jarvis"
    assert WakePhrase(text="ei jarvis").tokens == ("ei", "jarvis")


def test_parse_phrases_reads_the_configuration_list() -> None:
    phrases = parse_phrases("jarvis, jarves , ", max_edit_distance=0)

    assert [phrase.text for phrase in phrases] == ["jarvis", "jarves"]
    assert all(phrase.max_edit_distance == 0 for phrase in phrases)


@pytest.mark.parametrize("raw", ["", "  ", ",,,"])
def test_an_empty_configuration_is_refused(raw: str) -> None:
    with pytest.raises(InvalidVoiceInputError):
        parse_phrases(raw)


def test_a_phrase_needs_content_and_a_sane_tolerance() -> None:
    with pytest.raises(InvalidVoiceInputError):
        WakePhrase(text="   ")
    with pytest.raises(InvalidVoiceInputError):
        WakePhrase(text="jarvis", max_edit_distance=-1)
