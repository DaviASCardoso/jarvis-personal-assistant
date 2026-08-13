"""Configuração dos MCP Servers, e a fronteira de secrets que ela define.

O arquivo (`mcp.json`, caminho em `JARVIS_MCP_CONFIG`) declara **como iniciar**
cada servidor. Ele nunca contém credencial: `env_keys` nomeia variáveis de
ambiente, e os valores são lidos do ambiente do processo pai, em memória, na hora
de iniciar o filho. Consequência prática — o arquivo é versionável sem risco, e
um teste assere que nenhum valor de `env_keys` aparece em log, evento ou mensagem
de erro ([ADR-0006](../../../../docs/adr/0006-configuration-vs-preferences-vs-state.md)).

O ambiente do processo filho é **explícito e mínimo**: `PATH`, o mínimo que o
sistema operacional exige para executar qualquer coisa, e as chaves pedidas. Não
é `os.environ` inteiro — menor privilégio aplicado à borda do processo. Um MCP
Server não tem por que herdar `JARVIS_GEMINI_API_KEY` só porque estava lá.

Exemplo:

```json
{
  "servers": {
    "workspace": {
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "./data/workspace"],
      "enabled": true,
      "timeout_seconds": 20,
      "startup_timeout_seconds": 10,
      "env_keys": ["WORKSPACE_TOKEN"]
    }
  }
}
```
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from jarvis.tools.errors import ToolConfigurationError

DEFAULT_TIMEOUT_SECONDS: Final = 20.0
DEFAULT_STARTUP_TIMEOUT_SECONDS: Final = 10.0

# O que qualquer processo precisa para iniciar, por sistema operacional. Nada
# além disto é herdado.
_BASE_ENV_KEYS: Final = (
    "PATH",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class McpServerSpec:
    server_id: str
    command: tuple[str, ...]
    enabled: bool = True
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS
    env_keys: tuple[str, ...] = ()
    cwd: str | None = None

    def __post_init__(self) -> None:
        if not self.command:
            raise ToolConfigurationError(f"{self.server_id}: command não pode ser vazio")
        if self.timeout_seconds <= 0 or self.startup_timeout_seconds <= 0:
            raise ToolConfigurationError(f"{self.server_id}: timeouts precisam ser positivos")


def load_mcp_config(path: Path) -> tuple[McpServerSpec, ...]:
    """Lê o arquivo de servidores. Arquivo ausente = nenhum servidor, sem erro.

    A ausência é um estado normal: todo o resto do Jarvis funciona sem MCP, e
    exigir o arquivo transformaria uma integração opcional em pré-requisito.
    """
    if not path.exists():
        return ()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ToolConfigurationError(f"não foi possível ler {path}: {error}") from error
    if not isinstance(raw, Mapping):
        raise ToolConfigurationError(f"{path}: o documento precisa ser um objeto JSON")

    servers = raw.get("servers", {})
    if not isinstance(servers, Mapping):
        raise ToolConfigurationError(f"{path}: 'servers' precisa ser um objeto")

    return tuple(
        _spec(str(server_id), entry, path=path) for server_id, entry in sorted(servers.items())
    )


def _spec(server_id: str, entry: object, *, path: Path) -> McpServerSpec:
    if not isinstance(entry, Mapping):
        raise ToolConfigurationError(f"{path}: '{server_id}' precisa ser um objeto")

    command = entry.get("command")
    if (
        not isinstance(command, Sequence)
        or isinstance(command, str)
        or not all(isinstance(item, str) for item in command)
    ):
        raise ToolConfigurationError(f"{path}: '{server_id}.command' precisa ser lista de textos")

    env_keys = entry.get("env_keys", [])
    if (
        not isinstance(env_keys, Sequence)
        or isinstance(env_keys, str)
        or not all(isinstance(item, str) for item in env_keys)
    ):
        raise ToolConfigurationError(f"{path}: '{server_id}.env_keys' precisa ser lista de textos")

    cwd = entry.get("cwd")
    return McpServerSpec(
        server_id=server_id,
        command=tuple(str(item) for item in command),
        enabled=entry.get("enabled", True) is not False,
        timeout_seconds=_number(entry.get("timeout_seconds"), DEFAULT_TIMEOUT_SECONDS),
        startup_timeout_seconds=_number(
            entry.get("startup_timeout_seconds"), DEFAULT_STARTUP_TIMEOUT_SECONDS
        ),
        env_keys=tuple(str(item) for item in env_keys),
        cwd=str(cwd) if isinstance(cwd, str) else None,
    )


def _number(raw: object, fallback: float) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return fallback
    return float(raw)


def child_environment(spec: McpServerSpec, environ: Mapping[str, str]) -> dict[str, str]:
    """Monta o ambiente mínimo do processo filho.

    Uma chave declarada em `env_keys` e ausente do ambiente simplesmente não é
    passada — cabe ao servidor reclamar do que falta. Falhar aqui esconderia a
    mensagem útil dele atrás de uma nossa.
    """
    environment = {key: environ[key] for key in _BASE_ENV_KEYS if environ.get(key)}
    # Acrescentado, não herdado: MCP é UTF-8 no fio, e o padrão de um processo
    # Python em Windows ainda é a codificação do console. Um servidor que escreve
    # cp1252 produz uma resposta ilegível — e o sintoma parece "servidor caiu".
    environment["PYTHONIOENCODING"] = "utf-8"
    for key in spec.env_keys:
        value = environ.get(key)
        if value:
            environment[key] = value
    return environment
