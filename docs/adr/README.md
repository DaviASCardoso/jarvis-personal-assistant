# Architecture Decision Records

Este diretório registra decisões arquiteturais do Jarvis que são difíceis de
reverter e que fundamentam os contratos em
[`../architecture-contracts.md`](../architecture-contracts.md).

## Quando criar um ADR

Crie um ADR quando a decisão for:

- **difícil/cara de reverter** depois que houver código real sobre ela; e
- **arquitetural** — afeta a forma como componentes se relacionam, não um
  detalhe interno de um único componente; e
- houve uma **alternativa real considerada** e descartada, não uma escolha
  óbvia sem trade-off.

Não crie ADR para: escolha de nomes de campos, formato exato de um schema,
detalhes que podem mudar sem afetar outros componentes, ou qualquer decisão
já reversível de forma barata. Esses detalhes vivem em
`architecture-contracts.md` ou na documentação do componente, não aqui.

## Convenção de nomenclatura

```text
NNNN-titulo-curto-em-kebab-case.md
```

Numeração sequencial, sem reuso de número mesmo que um ADR seja superado.

## Template

```markdown
# NNNN. Título da decisão

**Status:** Accepted | Superseded by ADR-NNNN
**Data:** AAAA-MM-DD

## Contexto

Qual problema/força está em jogo. O que motivou a decisão ser tomada agora.

## Decisão

O que foi decidido, de forma direta.

## Alternativas consideradas

Alternativas reais avaliadas e por que foram descartadas.

## Consequências

O que fica mais fácil, o que fica mais difícil, e o que essa decisão não
resolve.
```

## Ciclo de vida

Um ADR aceito não é editado para refletir uma mudança de decisão — uma
mudança de decisão gera um **novo ADR**, que marca o anterior como
`Superseded by ADR-NNNN`. Isso preserva o histórico de por que a decisão
original fazia sentido no momento em que foi tomada.

## Índice

| ADR | Título | Status |
|---|---|---|
| [0001](0001-ports-and-adapters-dependency-rule.md) | Ports & Adapters como regra de dependência | Accepted |
| [0002](0002-llm-provider-abstraction.md) | Abstração de LLM Provider e separação de Embedding Provider | Accepted |
| [0003](0003-policy-engine-safety-authority.md) | Policy Engine como autoridade determinística de segurança | Accepted |
| [0004](0004-event-immutability-and-timestamps.md) | Imutabilidade de evento e semântica de timestamps | Accepted |
| [0005](0005-skill-tool-mcp-distinction.md) | Distinção entre Skill, Tool, MCP Server e MCP Tool | Accepted |
| [0006](0006-configuration-vs-preferences-vs-state.md) | Configuração vs. Secrets vs. Preferências vs. Estado | Accepted |
| [0007](0007-sqlite-event-store.md) | SQLite como armazenamento do Event Store | Accepted |
| [0008](0008-synchronous-in-process-event-bus.md) | Event Bus síncrono em processo | Accepted |
| [0009](0009-sqlite-memory-storage.md) | SQLite como armazenamento do Memory System | Accepted |
| [0010](0010-immutable-memory-and-supersession.md) | Memória imutável, com supersessão em vez de sobrescrita | Accepted |
| [0011](0011-gemini-rest-llm-adapter.md) | Gemini em nuvem, via REST da stdlib, como primeiro `LLMProvider` | Accepted |
| [0012](0012-core-owned-structured-decisions.md) | `Decision` como JSON validado no Core, sem tool-calling do vendor | Accepted |
| [0013](0013-single-use-policy-approval.md) | `PolicyApproval` como capacidade de uso único, validada pelo emissor | Accepted |
| [0014](0014-confirmation-state-and-event-answers.md) | Confirmação: ação pendente como estado; resposta do usuário como evento | Accepted |
| [0015](0015-stdlib-stdio-mcp-client.md) | Cliente MCP próprio, síncrono, sobre stdio da biblioteca padrão | Accepted |
| [0016](0016-action-execution-orchestrator.md) | `jarvis/execution` como único caminho até uma Skill | Accepted |
| [0017](0017-audit-trail-as-events.md) | Trilha de auditoria como eventos, sem store de auditoria próprio | Accepted |
| [0018](0018-memory-writes-outside-the-policy-engine.md) | Proposta de memória aplicada pelo composition root, fora do Policy Engine | Accepted |
| [0019](0019-gemini-action-parameters-as-json-text.md) | `action.parameters` transportado como texto JSON no adapter Gemini | Accepted |
| [0020](0020-audio-io-ports-and-optional-backend.md) | Captura e reprodução de áudio como ports, com backend em extra opcional | Accepted |
| [0021](0021-wake-word-without-local-ai.md) | Wake word sem IA local: gate determinístico e verificação por transcrição | Accepted |
| [0022](0022-cloud-speech-over-stdlib-rest.md) | STT e TTS em nuvem por REST da stdlib, com ports separados por papel | Accepted |
| [0023](0023-single-resident-process.md) | `jarvis run`: um processo residente para voz e painel | Accepted |
| [0024](0024-observability-panel-as-snapshot-reader.md) | Painel de observabilidade como leitor de snapshot, somente leitura | Accepted |
| [0025](0025-voice-transcripts-as-operational-state.md) | Transcrição de voz como estado operacional, nunca como evento | Accepted |
| [0026](0026-decision-log-as-events-built-from-primitives.md) | Decision Log como projeção de eventos já existentes | Accepted |
| [0027](0027-background-tasks-ticked-not-scheduled.md) | Tarefas de fundo avançadas por tick, sem scheduler próprio | Accepted |
| [0028](0028-console-channel-for-desktop-notifications.md) | Canal de console como primeiro canal de notificação | Accepted |
| [0029](0029-proactivity-opt-in-layers.md) | Autonomia real em três interruptores independentes; automação condicional sem LLM | Accepted |
| [0030](0030-psutil-as-a-normal-dependency.md) | `psutil` como dependência normal, não extra opcional | Accepted |
| [0031](0031-command-allowlist-execution-model.md) | `computer.open_app`/`computer.run_command`: só argv de uma allowlist, nunca comando livre | Accepted |
