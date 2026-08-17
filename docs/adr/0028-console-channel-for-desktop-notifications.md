# 0028. Canal "desktop" do Notification Manager é console/log, não um toast nativo

**Status:** Accepted
**Data:** 2026-08-17

## Contexto

A subfase 7.3 do [roadmap](../../ROADMAP.md) pede "implementar desktop
notification" como parte do `NotificationManager`. O Jarvis roda hoje em
Windows, sem instalação de serviço, sem GUI própria — a superfície visual que
já existe é o terminal onde `jarvis run` roda e o painel de observabilidade
(Fase 6, ADR-0024).

Um toast nativo do Windows sem dependência nova é tecnicamente alcançável —
via `subprocess` chamando `powershell.exe` e a API WinRT
(`Windows.UI.Notifications.ToastNotificationManager`) — mas exige interpolar
`title`/`body` de uma `Notification` (que pode ter vindo, na ponta, de um
payload de evento externo) dentro de um comando de shell. Evitar isso por
completo (parâmetros nunca chegam a um shell) exigiria uma camada de
serialização própria (script fixo lendo variáveis de ambiente, ou arquivo
temporário) só para este canal — complexidade real para uma capacidade que
`ROADMAP.md` regra 11 pede para não introduzir sem necessidade concreta.

## Decisão

Nesta fase, o canal "desktop" do `NotificationChannel` é
`ConsoleNotificationChannel`: uma linha estruturada em stdout/stderr (por
padrão `stderr`, mesmo destino de `configure_logging`). Nenhuma dependência
nova, nenhum `subprocess`, nenhuma superfície de injeção de comando —
`title`/`body` nunca atravessam um shell.

`NotificationChannel` continua sendo um port pequeno (`send(notification) ->
DeliveryResult`), então um adapter de toast nativo — via WinRT/PowerShell,
com o conteúdo passado por variável de ambiente ou arquivo, nunca
interpolado em texto de comando — pode entrar depois sem tocar
`NotificationManager`, `InterruptionPolicy` nem os testes existentes: é
literalmente outro `NotificationChannel` na lista `channels=[...]` que o
composition root monta.

## Alternativas consideradas

- **Toast nativo via `subprocess`/PowerShell agora**: descartado por risco de
  injeção de comando se o conteúdo fosse interpolado diretamente (viola a
  prioridade de segurança do projeto), e por introduzir acoplamento a uma
  plataforma específica sem que o roadmap exija isso explicitamente — o
  Jarvis já roda em modo texto/voz sem GUI própria.
- **Biblioteca de terceiros (`win10toast`, `plyer`)**: dependência nova sem
  necessidade concreta medida; o projeto prioriza a biblioteca padrão sempre
  que ela resolve o problema (aqui resolve: `print`/log já entrega o
  requisito de "uma notificação visível sem interromper o processo").
- **Nenhum canal "desktop" nesta fase**: deixaria o checklist da 7.3
  incompleto sem justificativa — o console é a superfície visual honesta que
  este agente pessoal, hoje, de fato tem.

## Consequências

- `jarvis run` num terminal mostra notificações proativas como linhas
  destacadas, sem depender de o SO ter suporte a toast nem de o processo ter
  foco de tela.
- Nenhum teste de `jarvis.notify` precisa de ambiente Windows, GUI ou
  permissão de notificação do sistema — a suíte roda igual em qualquer SO.
- **Custo aceito:** sem o processo visível (terminal minimizado, `jarvis run`
  em background), uma notificação "desktop" não aparece de fato na tela do
  usuário nesta fase. O painel de observabilidade (Fase 6) continua sendo a
  segunda superfície — os toasts que ele já renderiza (ADR-0024) são de
  eventos existentes, não deste canal, e não se sobrepõem.
- **Gatilho para reconsiderar:** pedido explícito de um toast nativo de
  verdade. Entra como um adapter novo atrás do mesmo port, com o conteúdo
  passado sem jamais tocar um shell interpolado.
