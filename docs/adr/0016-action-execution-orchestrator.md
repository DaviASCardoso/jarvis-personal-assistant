# 0016. `jarvis/execution` como único caminho até uma Skill

**Status:** Accepted
**Data:** 2026-08-13

## Contexto

A cadeia `Decision → Policy → Skill → Tool Router → MCP` precisa de alguém que a
percorra: que resolva o nome da skill no registry, valide os parâmetros, monte o
`PolicyRequest`, consuma a aprovação, chame o handler e registre a auditoria.

Os contratos existentes dizem, com precisão, quem **não** pode ser esse alguém:

- o Agent Runtime não executa ações ([ADR-0003](0003-policy-engine-safety-authority.md));
- uma Skill não conhece internals do Policy Engine (`architecture-contracts.md §3.6`);
- o Tool Router não conhece regras de negócio de Skill nem decide autorização (§3.7);
- o Policy Engine não conhece Skills nem Tools (§3.5).

Os quatro estão proibidos de fechar o triângulo. Nenhum contrato nomeia quem
fecha — porque, até a Fase 5, não havia o que fechar.

## Decisão

Criar `jarvis/execution/` como componente de Core, e declará-lo o **único**
autorizado a conhecer `jarvis.policy`, `jarvis.skills` e `jarvis.tools` ao mesmo
tempo. `ActionExecutor` é seu serviço de aplicação.

Junto com ele, `ToolAccess`: o objeto que uma Skill efetivamente segura. Uma
Skill **não** recebe o `ToolRouter` — recebe um `ToolAccess` amarrado a uma
execução e limitado às tools que ela própria declarou em `required_tools`,
construído apenas depois de `PolicyEngine.consume(approval)` ter passado.

Duas propriedades caem desse desenho, e as duas são testadas:

- **menor privilégio por execução** (`PHASE-5.md §33`): uma Skill de leitura que
  tentasse chamar uma tool de escrita é recusada com `ToolNotPermittedError`,
  mesmo com aprovação válida em mãos;
- **não há caminho de bypass**: para chegar ao router é preciso um `ToolAccess`;
  para ter um `ToolAccess` é preciso ter passado pelo Policy Engine.

Um teste arquitetural varre a AST de `src/` e falha se qualquer módulo fora de
`jarvis/execution/orchestrator.py` construir `ToolAccess`.

O executor **retorna** desfechos em vez de levantar exceções nos casos previstos
(`denied`, `awaiting_confirmation`, `expired`, `duplicate`): negar não é falha
(`architecture-contracts.md §13`), e o agente precisa poder relatar a negação ao
usuário.

## Alternativas consideradas

- **Agent Runtime orquestra**: descartada — viola o ADR-0003 diretamente, e
  falharia no teste arquitetural que a Fase 4 já havia deixado pronto
  (`test_no_path_from_the_agent_to_execution`, com os nomes reservados desde
  então).
- **Skill Registry orquestra**: descartada — `jarvis.skills` passaria a importar
  `jarvis.policy`, contra o contrato §3.6, e "Skill não conhece o Policy Engine"
  deixaria de ser enunciável como regra de import.
- **Tool Router orquestra**: descartada — o router é o ponto onde a chamada já
  chega autorizada (§3.7). Dar-lhe a decisão de autorização colapsaria as duas
  responsabilidades no mesmo lugar.
- **Skill recebe o `ToolRouter` inteiro**: descartada — funcionaria, e perderia o
  escopo por execução. `required_tools` viraria documentação, e a única barreira
  seria a política, que opera na granularidade da Skill e não da chamada.

## Consequências

- Um quinto pacote em `src/jarvis/`, e um grafo de dependências acíclico em que
  cada aresta proibida é uma linha de teste.
- `jarvis.policy`, `jarvis.skills` e `jarvis.tools` permanecem independentes e
  testáveis isoladamente — nenhum deles precisa dos outros dois para rodar.
- O composition root ganha um passo de montagem a mais
  (`build_action_executor`), concentrado em `cli.py` como todo o resto.
- **Custo aceito:** uma indireção a mais entre "o agente decidiu" e "a skill
  rodou". É o mesmo custo que o ADR-0003 já havia aceitado ao separar proposta de
  execução, agora com um dono explícito.
- Fases futuras que precisem executar ações (Trigger Engine na 7.1, Background
  Tasks na 7.5) acionam `ActionExecutor` — não reimplementam a cadeia, e não
  ganham acesso direto a Skills ou Tools.
