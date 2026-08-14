"""Erros do painel de observabilidade."""

from typing import ClassVar

from jarvis.errors import DomainError, InfrastructureError


class InterfaceError(DomainError):
    """Uso inválido da camada de interface."""


class PanelError(InterfaceError):
    """Configuração de painel que não pode ser servida.

    O caso concreto que existe hoje: um `host` que não seja local. Abrir o painel
    para a rede exigiria autenticação, e autenticação é multiusuário — que o
    escopo desta fase exclui explicitamente.
    """


class PanelAddressInUseError(InfrastructureError):
    """A porta do painel já está ocupada."""

    retryable: ClassVar[bool] = False
