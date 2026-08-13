"""O vocabulário de risco, permissão e confirmação.

Módulo **folha**: não importa nada de `jarvis`. É deliberado — é o único ponto de
`jarvis.policy` que `jarvis.skills` pode tocar, e um teste arquitetural garante
que continue assim. Skills declaram valores *deste* vocabulário; a decisão que se
toma a partir deles mora em `engine.py`, longe do alcance de quem declara — ver
§8.4 de [`architecture-contracts.md`](../../../docs/architecture-contracts.md).

Duas grandezas, e não uma:

- `RiskLevel` é escalar e ordenado — responde "quão perigoso?";
- `Effect` é categórico — responde "perigoso *como*?".

`PHASE-5.md §32` pede distinguir leitura, alteração, ação destrutiva, ação física
e comunicação externa. Um escalar não expressa isso: `start_print` e
`delete_file` podem ser igualmente arriscados e ainda assim merecer políticas
diferentes.
"""

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import Final

CAPABILITY_PATTERN: Final = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*:[a-z0-9]+(?:_[a-z0-9]+)*$")


class RiskLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _RISK_ORDER[self]

    def at_least(self, other: "RiskLevel") -> bool:
        """Comparação por severidade.

        `StrEnum` compara como texto, e alfabeticamente `critical < low` — o
        oposto do que a política precisa. Por isso a ordem é explícita e a
        comparação passa por aqui, nunca por `>=` direto.
        """
        return self.rank >= other.rank


_RISK_ORDER: Final[dict[RiskLevel, int]] = {
    RiskLevel.NONE: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


class ConfirmationRequirement(StrEnum):
    """O que a Skill *acredita* que deveria ser exigido dela.

    Insumo para o Policy Engine, nunca autorização: uma Skill que declare `NEVER`
    continua sujeita à denylist, ao teto de risco e às regras de efeito.
    """

    NEVER = "never"
    CONDITIONAL = "conditional"
    ALWAYS = "always"


class Effect(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    PHYSICAL = "physical"
    EXTERNAL_COMMUNICATION = "external_communication"
    SPEND = "spend"


class Idempotency(StrEnum):
    """Se repetir a execução é seguro.

    `SAFE` é o que autoriza o Tool Router a repetir uma chamada que falhou de
    forma transitória. `UNSAFE` proíbe: um timeout não prova que a operação não
    aconteceu do outro lado (`PHASE-5.md §19`).
    """

    SAFE = "safe"
    UNSAFE = "unsafe"


class InvalidPolicyVocabularyError(ValueError):
    """Um valor de vocabulário inválido — tipicamente vindo de configuração.

    `ValueError` e não `DomainError` de propósito: este módulo é folha e não
    importa `jarvis.errors`. Quem carrega configuração traduz.
    """


def require_capability(value: str, *, field_name: str = "capability") -> str:
    if not CAPABILITY_PATTERN.fullmatch(value):
        raise InvalidPolicyVocabularyError(
            f"{field_name} precisa ser 'dominio:verbo', recebido {value!r}"
        )
    return value


def parse_capabilities(raw: Iterable[str] | str) -> frozenset[str]:
    """Lê uma lista de capacidades de configuração (string com vírgulas ou já iterável).

    Falha alta em item inválido: uma capacidade escrita errada num `.env` que
    fosse ignorada em silêncio viraria uma allowlist menor do que o operador
    pensa ter — ou maior.
    """
    items = raw.split(",") if isinstance(raw, str) else raw
    return frozenset(require_capability(item.strip()) for item in items if item.strip())


def parse_effects(raw: Iterable[str] | str) -> frozenset[Effect]:
    items = raw.split(",") if isinstance(raw, str) else raw
    return frozenset(_parse_effect(item.strip()) for item in items if item.strip())


def _parse_effect(value: str) -> Effect:
    try:
        return Effect(value)
    except ValueError as error:
        raise InvalidPolicyVocabularyError(
            f"efeito desconhecido: {value!r}; use um de {', '.join(item.value for item in Effect)}"
        ) from error


def parse_risk(value: str) -> RiskLevel:
    try:
        return RiskLevel(value)
    except ValueError as error:
        raise InvalidPolicyVocabularyError(
            f"nível de risco desconhecido: {value!r}; use um de "
            f"{', '.join(item.value for item in RiskLevel)}"
        ) from error


def parse_names(raw: Iterable[str] | str) -> frozenset[str]:
    """Lista de nomes livres (denylist de skills), sem validação de forma.

    Um nome que não exista simplesmente nunca casa — negar por engano um nome
    inexistente é inofensivo, e recusar a configuração inteira por causa de uma
    entrada obsoleta seria pior.
    """
    items = raw.split(",") if isinstance(raw, str) else raw
    return frozenset(item.strip() for item in items if item.strip())
