# 0015. Cliente MCP próprio, síncrono, sobre stdio da biblioteca padrão

**Status:** Accepted
**Data:** 2026-08-13

## Contexto

A Fase 5 precisa falar MCP para que o Tool Router tenha um backend externo — é o
que torna a arquitetura extensível a Gmail, Calendar, Todoist ou uma impressora
3D sem tocar no Core. A questão é **como** falar o protocolo.

Duas restrições pesam mais que qualquer outra:

- o Jarvis é **síncrono por decisão registrada**
  ([ADR-0008](0008-synchronous-in-process-event-bus.md)): o Event Bus, os
  consumers e o CLI são todos síncronos;
- `PHASE-5.md §38/§44` pedem não adicionar dependências pesadas e manter o CI
  determinístico, rápido, gratuito e sem secrets.

Há um precedente direto no repositório: o [ADR-0011](0011-gemini-rest-llm-adapter.md)
já preferiu falar com o Gemini por `urllib` da stdlib a adotar o SDK do vendor.

## Decisão

Implementar um cliente MCP próprio, **síncrono**, sobre **stdio + JSON-RPC 2.0
delimitado por linha**, usando apenas `subprocess`, `json`, `threading` e `queue`.

O subconjunto implementado fecha em quatro mensagens: `initialize`,
`notifications/initialized`, `tools/list`, `tools/call`. Resources e prompts do
MCP ficam de fora — não há consumidor para eles nesta fase.

Três detalhes de implementação que a portabilidade impôs, e que valem registro
porque não são óbvios:

1. **Thread leitora + `queue`, nunca `select`.** `selectors`/`select` não
   funcionam sobre pipes no Windows, e este projeto é desenvolvido em Windows e
   testado em Linux no CI. Uma thread que só faz `for line in stdout` e empurra
   para uma `Queue` funciona igual nos dois e dá timeout de graça via
   `Queue.get(timeout=...)`.
2. **`stderr=DEVNULL`.** Capturar stderr exigiria uma segunda thread para não
   travar o pipe, e o que viesse de lá acabaria em log — inclusive o que um
   servidor mal-comportado imprimir sobre a própria credencial.
3. **UTF-8 forçado nas duas pontas** (`errors="replace"` na leitura,
   `PYTHONIOENCODING=utf-8` no ambiente do filho). MCP é UTF-8 no fio, mas o
   padrão de um processo Python no Windows ainda é a codificação do console; sem
   isso, um acento na descrição de uma tool derruba a thread leitora com
   `UnicodeDecodeError` e o sintoma aparece como "o servidor sumiu".

## Alternativas consideradas

- **SDK oficial `mcp`**: descartada. É async-first; adotá-la forçaria asyncio no
  Event Bus, no CLI e em toda a suíte de testes, revertendo na prática o
  ADR-0008. O ganho — não escrever ~200 linhas de framing JSON-RPC — não paga uma
  mudança de modelo de concorrência no sistema inteiro, e ainda acrescentaria uma
  dependência e sua árvore.
- **Transporte HTTP/SSE**: descartada por ora. Nenhum servidor que este projeto
  pretende usar no curto prazo o exige, e stdio é o transporte local canônico do
  MCP. Acrescentá-lo depois é um segundo `Transport`, não uma reescrita — o
  Protocol já existe.
- **Adiar MCP para uma fase futura**: descartada. Deixaria o Tool Router com um
  único backend, e um contrato de `Tool` com um só implementador acaba virando um
  espelho desse implementador — exatamente o acoplamento que o
  [ADR-0005](0005-skill-tool-mcp-distinction.md) existe para evitar.

## Consequências

- Zero dependências novas na fase inteira.
- O cliente é testável em dois níveis: o protocolo como função pura (texto entra,
  estrutura sai) e o cliente contra um `FakeTransport` em memória — os dois sem
  processo. A integração com processo real usa `tests/mcp_fake_server.py`, que é
  nosso, local e determinístico.
- **Risco assumido:** um cliente artesanal pode divergir de um servidor real em
  detalhes que o servidor falso não exercita. Mitigação: o subconjunto é pequeno
  e estável, a versão de protocolo é declarada explicitamente, e o
  `ToolProtocolError` distingue "não entendi a resposta" de "o servidor caiu" —
  o que torna a divergência diagnosticável em vez de misteriosa.
- **Gatilho para reconsiderar:** um servidor real que exija negociação de
  capacidades além do handshake mínimo, ou que só ofereça HTTP/SSE. Aí o custo do
  SDK (ou de uma ponte async) passa a se pagar, e este ADR deve ser superado.
- Um servidor que exponha uma tool com nome impossível de qualificar como
  `ToolId` tem essa tool **pulada**, não a descoberta inteira derrubada; o nome
  recusado aparece em `jarvis tools list`.
