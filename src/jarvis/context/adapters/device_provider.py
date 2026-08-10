"""Device Provider: a identidade da máquina onde o Jarvis roda.

`platform.node()` da biblioteca padrão é o limite do que dá para observar com
segurança nesta fase: nada de automação do sistema operacional, processo ativo,
janela em foco ou uso de recursos — isso é escopo da subfase 8.1, com as
permissões correspondentes.

Quando o sistema não sabe o próprio nome, `platform.node()` devolve string vazia.
Isso vira **ausência**, não um valor inventado (contracts §6).
"""

import platform
from collections.abc import Callable
from datetime import datetime

from jarvis.context.errors import ContextProviderError
from jarvis.context.model import ContextUpdate
from jarvis.context.observation import Observation


class LocalDeviceProvider:
    def __init__(
        self, *, hostname: Callable[[], str] = platform.node, name: str = "device"
    ) -> None:
        self._hostname = hostname
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def observe(self, now: datetime) -> ContextUpdate:
        try:
            device_id = self._hostname()
        except OSError as error:
            raise ContextProviderError("não foi possível identificar o dispositivo") from error

        if not device_id.strip():
            return ContextUpdate()

        return ContextUpdate(
            device_id=Observation(
                value=device_id,
                observed_at=now,
                source=f"provider:{self._name}",
            )
        )
