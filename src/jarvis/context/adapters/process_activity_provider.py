"""Process Activity Provider: quantos processos "relevantes" estão rodando (Fase 8.1).

"Relevante" é decisão de configuração (`JARVIS_COMPUTER_RELEVANT_PROCESSES`),
nunca uma lista embutida no provider — o que conta como relevante pertence a
quem configura o Jarvis, não a este módulo. Allowlist vazia (default) é
**ausência**, não "zero processos relevantes": o provider nunca observou
nada porque ninguém disse o que observar, e a distinção importa pelo mesmo
motivo do contrato §6 — não inferir na ausência de configuração.
"""

from collections.abc import Callable, Sequence
from datetime import datetime

import psutil

from jarvis.context.model import ContextUpdate
from jarvis.context.observation import Observation


def _default_running_process_names() -> Sequence[str]:
    names: list[str] = []
    for process in psutil.process_iter(["name"]):
        try:
            name = process.info.get("name")
        except psutil.Error:
            continue
        if isinstance(name, str) and name:
            names.append(name)
    return names


class ProcessActivityProvider:
    def __init__(
        self,
        *,
        relevant_process_names: frozenset[str] = frozenset(),
        running_process_names: Callable[[], Sequence[str]] = _default_running_process_names,
        name: str = "process_activity",
    ) -> None:
        self._relevant = frozenset(item.lower() for item in relevant_process_names)
        self._running = running_process_names
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def observe(self, now: datetime) -> ContextUpdate:
        if not self._relevant:
            return ContextUpdate()

        try:
            running = self._running()
        except (OSError, psutil.Error):
            return ContextUpdate()

        count = sum(1 for item in running if item.lower() in self._relevant)
        return ContextUpdate(
            relevant_process_count=Observation(
                value=count, observed_at=now, source=f"provider:{self._name}"
            )
        )
