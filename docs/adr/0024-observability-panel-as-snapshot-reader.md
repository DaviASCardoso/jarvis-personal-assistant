# 0024. Painel de observabilidade como leitor de snapshot, somente leitura

**Status:** Accepted
**Data:** 2026-08-14

## Contexto

A especificação da Fase 6 pede uma interface visual que exponha o estado interno
do Jarvis — eventos, contexto, memórias, decisões, ferramentas e conversa — e diz
que ela deve ser "local, simples, leve e reativa", e que **não deve manter estado
próprio**: a fonte da verdade continua sendo Event Store, Context System e Memory
System.

Duas decisões precisam ser tomadas juntas, porque uma condiciona a outra:

1. **o que a interface recebe** — entidades de domínio ou uma projeção pronta;
2. **o que a interface pode fazer** — só mostrar, ou também acionar.

A segunda importa mais do que parece: a Fase 5 construiu uma cadeia de
autorização inteira (`Decision → Policy → Skill → Tool`) com um único caminho até
uma Tool ([ADR-0016](0016-action-execution-orchestrator.md)). Uma rota de escrita
no painel seria um segundo.

## Decisão

**O painel é um leitor de `PanelSnapshot`, e nada além disso.**

1. `ObservabilityService` recebe **quatro funções de leitura** injetadas pelo
   composition root — o mesmo desenho de `AgentRuntime(context_reader=...)` — e
   devolve um `PanelSnapshot` de view models planos e serializáveis. O pacote
   `jarvis.interface` não abre banco, não conhece adapter e não sabe o que é
   SQLite.
2. **Nenhuma rota de escrita existe.** `POST`, `PUT`, `DELETE` e `PATCH`
   respondem 405 em qualquer caminho, e um teste varre a AST para garantir que o
   único `do_*` implementado é `do_GET`. Confirmar uma ação continua sendo
   assunto do CLI ([ADR-0014](0014-confirmation-state-and-event-answers.md)) e da
   voz.
3. **Bind fixo em loopback**, verificado na construção: um host que não seja
   `127.0.0.1`/`localhost`/`::1` é recusado com `PanelError`. Expor na rede
   exigiria autenticação, e autenticação é multiusuário — explicitamente fora do
   escopo da fase.
4. **`http.server` da biblioteca padrão**, com uma página única autocontida
   (HTML+CSS+JS inline), servida sob uma CSP que não permite nenhuma origem
   externa. Atualização por SSE, com fallback para polling depois de duas falhas.
5. **Degradação honesta**: cada leitura é embrulhada; um banco travado degrada
   um bloco, aparece em `PanelSnapshot.degraded` e é mostrado na tela. Mostrar
   vazio como se fosse ausência seria mentir sobre o estado do sistema — que é
   exatamente o que o painel existe para não fazer.

## Alternativas consideradas

- **TUI com `curses`**: exigiria `windows-curses` (dependência nova, e o projeto
  é desenvolvido no Windows), e reimplementaria layout e scroll que o navegador
  já dá de graça.
- **Framework web (Flask/FastAPI) com front-end compilado**: dependências,
  build, e um `node_modules` para um painel de sete cartões.
- **Painel com rotas de escrita** (confirmar ação, executar skill): descartada
  pelo motivo do §2. É a decisão mais importante deste ADR, e a mais fácil de
  reverter por engano depois — por isso está aqui e num teste.
- **Entregar entidades de domínio à página** (serializar `RecordedEvent`,
  `StoredMemory`): faria qualquer campo novo do domínio vazar para a resposta
  HTTP sem ninguém decidir isso. A serialização é escrita à mão, campo a campo,
  pelo mesmo motivo.
- **Expor o painel na rede local** ("é só a minha casa"): sem autenticação, é
  uma janela para o estado interno do assistente pessoal de alguém.

## Consequências

- A regra "a interface nunca acessa SQLite, MCP, Skills ou LLM" vira uma lista de
  imports proibidos em `tests/test_interface_architecture.py`.
- O payload de um evento de **fonte externa** nunca vira texto de tela: o resumo
  da linha do tempo é derivado do tipo e de uma allowlist de campos de
  identidade que o próprio Jarvis escreve. Um e-mail não aparece no painel.
- A página funciona offline, sem CDN, e não consegue exfiltrar o que mostra nem
  que alguém injete conteúdo num resumo.
- **Custo aceito:** o painel mostra o que o snapshot tinha quando foi montado, e
  não uma consulta ao vivo. O `as_of` na tela diz de quando é.
- **Não resolve:** histórico consultável de decisões, que depende da subfase 7.4.
  Até lá o painel mostra a decisão do turno em curso e a trilha de auditoria da
  Fase 5 — e `DecisionCard` já tem a forma que a 7.4 vai preencher.
