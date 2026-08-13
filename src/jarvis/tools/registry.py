"""Registry de Tools: o catálogo do **ambiente**, não do domínio.

`PHASE-5.md §25`: "O registry não deve virar uma segunda fonte de verdade para o
domínio. Ele representa capacidades disponíveis no ambiente." Consequência
prática: vive em memória, é refeito a cada processo e não é persistido. Cache de
catálogo só se justificaria com custo de descoberta medido, e não há — o backend
local é estático e os MCP Servers são processos locais.

Um backend que falha na descoberta **não derruba o processo**: fica registrado
como degradado, aparece assim em `jarvis tools list`, e uma Skill que dependa de
uma tool ausente é negada pelo Policy Engine antes de executar — em vez de
falhar no meio do caminho, com metade dos efeitos já produzidos.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from jarvis.tools.errors import ToolError, ToolNotFoundError
from jarvis.tools.ports import ToolBackend
from jarvis.tools.tool import ToolDescriptor, ToolId, require_tool_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class BackendStatus:
    backend_id: str
    available: bool
    tool_count: int
    detail: str = ""


class ToolRegistry:
    """Mapa `ToolId → (backend, descriptor)`, construído por descoberta."""

    def __init__(self) -> None:
        self._backends: dict[str, ToolBackend] = {}
        self._descriptors: dict[ToolId, ToolDescriptor] = {}
        self._owners: dict[ToolId, ToolBackend] = {}
        self._statuses: dict[str, BackendStatus] = {}

    def register_backend(self, backend: ToolBackend) -> None:
        if backend.backend_id in self._backends:
            raise ToolError(f"backend já registrado: {backend.backend_id}")
        self._backends[backend.backend_id] = backend
        self._statuses[backend.backend_id] = BackendStatus(
            backend_id=backend.backend_id, available=False, tool_count=0, detail="não descoberto"
        )

    def refresh(self) -> tuple[BackendStatus, ...]:
        """Redescobre tudo. Idempotente: substitui o catálogo inteiro."""
        self._descriptors.clear()
        self._owners.clear()

        for backend_id, backend in self._backends.items():
            try:
                discovered = backend.discover()
            except ToolError as error:
                # Detalhe do erro vai para o log; o status carrega só a categoria,
                # porque ele é impresso e pode acabar num relatório.
                logger.warning(
                    "tools.discovery_failed",
                    extra={"backend_id": backend_id, "error_type": type(error).__name__},
                    exc_info=error,
                )
                self._statuses[backend_id] = BackendStatus(
                    backend_id=backend_id,
                    available=False,
                    tool_count=0,
                    detail=type(error).__name__,
                )
                continue

            for descriptor in discovered:
                self._adopt(descriptor, backend)
            self._statuses[backend_id] = BackendStatus(
                backend_id=backend_id, available=True, tool_count=len(discovered)
            )
            logger.info(
                "tools.discovered",
                extra={"backend_id": backend_id, "tool_count": len(discovered)},
            )

        return self.statuses()

    def _adopt(self, descriptor: ToolDescriptor, backend: ToolBackend) -> None:
        if descriptor.backend_id != backend.backend_id:
            raise ToolError(
                f"backend {backend.backend_id} anunciou tool de {descriptor.backend_id}"
            )
        self._descriptors[descriptor.tool_id] = descriptor
        self._owners[descriptor.tool_id] = backend

    def get(self, tool_id: ToolId) -> ToolDescriptor:
        descriptor = self._descriptors.get(require_tool_id(tool_id))
        if descriptor is None:
            raise ToolNotFoundError(f"tool não registrada: {tool_id}")
        return descriptor

    def backend_for(self, tool_id: ToolId) -> ToolBackend:
        backend = self._owners.get(require_tool_id(tool_id))
        if backend is None:
            raise ToolNotFoundError(f"tool não registrada: {tool_id}")
        return backend

    def has(self, tool_id: ToolId) -> bool:
        return tool_id in self._descriptors

    def missing(self, tool_ids: Sequence[ToolId]) -> tuple[ToolId, ...]:
        """Quais das tools pedidas não estão disponíveis.

        É o que o executor consulta para negar uma Skill cujas ferramentas não
        existem, em vez de deixá-la começar e falhar no meio.
        """
        return tuple(tool_id for tool_id in tool_ids if tool_id not in self._descriptors)

    def list(self) -> tuple[ToolDescriptor, ...]:
        return tuple(self._descriptors[key] for key in sorted(self._descriptors))

    def statuses(self) -> tuple[BackendStatus, ...]:
        return tuple(self._statuses[key] for key in sorted(self._statuses))

    def close(self) -> None:
        """Encerra os backends. Uma falha não impede o encerramento dos demais."""
        for backend_id, backend in self._backends.items():
            try:
                backend.close()
            except Exception as error:
                logger.warning(
                    "tools.close_failed",
                    extra={"backend_id": backend_id, "error_type": type(error).__name__},
                    exc_info=error,
                )
