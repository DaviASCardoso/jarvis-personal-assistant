"""Reconhecimento da frase de ativação, sobre texto já transcrito.

Duas regras carregam quase todo o valor deste módulo:

1. **A frase só vale no primeiro token do enunciado.** "jarvis, apague o arquivo"
   ativa; "o jarvis do filme apaga tudo" não. Sem essa restrição, qualquer menção
   ao nome — inclusive vinda de uma TV ligada — viraria comando. Quem quiser
   "ei jarvis" registra a frase inteira em `JARVIS_WAKE_PHRASES`: tolerar uma
   palavra qualquer antes do nome reabriria exatamente o buraco que a regra
   fecha, porque o contraexemplo começa com "o".
2. **Tolerância de uma edição, e só em palavra longa.** Transcritores devolvem
   "jarves", "jarvez" e "járvis" com frequência; devolvem "e"→"a" com frequência
   ainda maior. Permitir distância 1 em token curto casaria com metade do
   dicionário.

O casamento é determinístico e opera sobre texto normalizado — nada aqui ouve
áudio.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from jarvis.voice.errors import InvalidVoiceInputError

#: Abaixo disso, distância de edição não é tolerada.
MIN_FUZZY_LENGTH: Final = 4

_NON_WORD: Final = re.compile(r"[^0-9a-z]+")


def normalize(text: str) -> str:
    """Minúsculas, sem acento, sem pontuação, espaços colapsados."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_WORD.sub(" ", stripped).strip()


def edit_distance(left: str, right: str, *, cap: int) -> int:
    """Levenshtein com corte: devolve `cap + 1` assim que passar do teto.

    O corte não é otimização prematura — é o que mantém a função barata quando o
    modo de wake word por transcrição a chama para cada token de cada segmento.
    """
    if left == right:
        return 0
    if abs(len(left) - len(right)) > cap:
        return cap + 1

    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        if min(current) > cap:
            return cap + 1
        previous = current
    return previous[-1]


@dataclass(frozen=True, slots=True, kw_only=True)
class WakePhrase:
    text: str
    max_edit_distance: int = 1

    def __post_init__(self) -> None:
        normalized = normalize(self.text)
        if not normalized:
            raise InvalidVoiceInputError("a frase de ativação não pode ser vazia")
        if self.max_edit_distance < 0:
            raise InvalidVoiceInputError("max_edit_distance não pode ser negativo")
        object.__setattr__(self, "text", normalized)

    @property
    def tokens(self) -> tuple[str, ...]:
        return tuple(self.text.split())


def parse_phrases(raw: str, *, max_edit_distance: int = 1) -> tuple[WakePhrase, ...]:
    """Lê a configuração `JARVIS_WAKE_PHRASES` (lista separada por vírgula)."""
    phrases = tuple(
        WakePhrase(text=item.strip(), max_edit_distance=max_edit_distance)
        for item in raw.split(",")
        if item.strip()
    )
    if not phrases:
        raise InvalidVoiceInputError("nenhuma frase de ativação configurada")
    return phrases


def _token_matches(candidate: str, expected: str, *, cap: int) -> bool:
    if candidate == expected:
        return True
    if cap <= 0 or len(expected) < MIN_FUZZY_LENGTH:
        return False
    return edit_distance(candidate, expected, cap=cap) <= cap


def matches(transcript: str, phrases: Sequence[WakePhrase]) -> tuple[str, str] | None:
    """Devolve `(frase, resto_do_enunciado)`, ou `None` se não houve ativação."""
    tokens = normalize(transcript).split()
    if not tokens:
        return None

    for phrase in phrases:
        expected = phrase.tokens
        end = len(expected)
        if end > len(tokens):
            continue
        if all(
            _token_matches(candidate, wanted, cap=phrase.max_edit_distance)
            for candidate, wanted in zip(tokens[:end], expected, strict=True)
        ):
            return phrase.text, " ".join(tokens[end:])
    return None
