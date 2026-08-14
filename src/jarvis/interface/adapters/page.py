"""A página do painel: um arquivo, sem CDN e sem build.

Tudo é inline — HTML, CSS e ~130 linhas de JS — porque um painel local que
depende de rede para se desenhar não é um painel local. A CSP servida junto
(`http_panel.py`) não permite nenhuma origem externa, então esta página **não
consegue** exfiltrar o que mostra nem que alguém injete conteúdo num resumo.

Toda inserção no DOM usa `textContent`, nunca `innerHTML`: o painel exibe texto
que passou por eventos e transcrições, e escapar é o mínimo.
"""

from typing import Final

PANEL_HTML: Final = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jarvis — painel</title>
<style>
  :root {
    color-scheme: dark;
    --bg: #0f1115; --card: #171a21; --line: #262b36; --text: #e6e9ef;
    --dim: #9aa3b2; --info: #6ea8fe; --ok: #5dd39e; --warn: #ffc857; --bad: #ff6b6b;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font: 14px/1.5 ui-sans-serif, system-ui, "Segoe UI", sans-serif; }
  header { position: sticky; top: 0; z-index: 5; background: var(--bg);
           border-bottom: 1px solid var(--line); padding: 12px 20px;
           display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  h1 { font-size: 15px; margin: 0; letter-spacing: .04em; text-transform: uppercase; }
  .state { font-weight: 600; padding: 3px 10px; border-radius: 999px;
           background: var(--line); color: var(--info); }
  .state[data-state="speaking"] { color: var(--ok); }
  .state[data-state="capturing"], .state[data-state="transcribing"] { color: var(--warn); }
  .state[data-state="idle"] { color: var(--dim); }
  .meta { color: var(--dim); font-size: 12px; }
  main { display: grid; gap: 14px; padding: 16px 20px 60px;
         grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); }
  section { background: var(--card); border: 1px solid var(--line);
            border-radius: 10px; overflow: hidden; display: flex; flex-direction: column; }
  section > h2 { margin: 0; padding: 10px 14px; font-size: 12px; letter-spacing: .08em;
                 text-transform: uppercase; color: var(--dim);
                 border-bottom: 1px solid var(--line); }
  ul { list-style: none; margin: 0; padding: 6px 0; max-height: 340px; overflow-y: auto; }
  li { padding: 6px 14px; border-bottom: 1px solid rgba(255,255,255,.03); }
  li:last-child { border-bottom: 0; }
  .row { display: flex; gap: 10px; align-items: baseline; }
  .row .grow { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .tag { font: 12px ui-monospace, SFMono-Regular, Consolas, monospace; color: var(--dim); }
  .sev-success { color: var(--ok); } .sev-warning { color: var(--warn); }
  .sev-danger { color: var(--bad); } .sev-info { color: var(--info); }
  .empty { padding: 14px; color: var(--dim); font-style: italic; }
  .bubble { padding: 8px 14px; }
  .bubble b { color: var(--info); font-weight: 600; }
  .bubble.assistant b { color: var(--ok); }
  #degraded { color: var(--warn); }
  #toasts { position: fixed; right: 18px; bottom: 18px; display: flex;
            flex-direction: column; gap: 8px; z-index: 10; max-width: 360px; }
  .toast { background: var(--card); border: 1px solid var(--line); border-left-width: 3px;
           border-radius: 8px; padding: 10px 12px; box-shadow: 0 6px 24px rgba(0,0,0,.4); }
  .toast.sev-danger { border-left-color: var(--bad); }
  .toast.sev-warning { border-left-color: var(--warn); }
  .toast.sev-success { border-left-color: var(--ok); }
  .toast strong { display: block; margin-bottom: 2px; }
</style>
</head>
<body>
<header>
  <h1>Jarvis</h1>
  <span class="state" id="voice-state" data-state="idle">idle</span>
  <span class="meta" id="voice-detail"></span>
  <span class="meta" id="as-of"></span>
  <span class="meta" id="degraded"></span>
</header>

<main>
  <section><h2>Conversa</h2><div id="conversation"></div></section>
  <section><h2>Eventos</h2><ul id="timeline"></ul></section>
  <section><h2>Contexto atual</h2><ul id="context"></ul></section>
  <section><h2>Memórias relevantes</h2><ul id="memories"></ul></section>
  <section><h2>Decisões</h2><ul id="decisions"></ul></section>
  <section><h2>Ações</h2><ul id="actions"></ul></section>
  <section><h2>Ferramentas</h2><ul id="tools"></ul></section>
</main>

<div id="toasts"></div>

<script>
(function () {
  var seenToasts = new Set();
  var failures = 0;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function time(value) {
    if (!value) { return ""; }
    return new Date(value).toLocaleTimeString("pt-BR");
  }

  function fill(id, items, build) {
    var host = document.getElementById(id);
    host.replaceChildren();
    if (!items || items.length === 0) {
      host.appendChild(el("li", "empty", "nada por enquanto"));
      return;
    }
    items.forEach(function (item) { host.appendChild(build(item)); });
  }

  function line(left, right, cls) {
    var li = el("li");
    var row = el("div", "row");
    row.appendChild(el("span", "grow " + (cls || ""), left));
    row.appendChild(el("span", "tag", right));
    li.appendChild(row);
    return li;
  }

  function render(state) {
    var voice = state.voice || {};
    var badge = document.getElementById("voice-state");
    badge.textContent = voice.state || "idle";
    badge.dataset.state = voice.state || "idle";
    document.getElementById("voice-detail").textContent =
      voice.last_transcript ? "\\u201c" + voice.last_transcript + "\\u201d" : "";
    document.getElementById("as-of").textContent = "atualizado " + time(state.as_of);
    document.getElementById("degraded").textContent =
      (state.degraded && state.degraded.length) ? "sem leitura: " + state.degraded.join(", ") : "";

    var conversation = document.getElementById("conversation");
    conversation.replaceChildren();
    if (!state.conversation || state.conversation.length === 0) {
      conversation.appendChild(el("div", "empty", "nenhuma conversa nesta sessão"));
    } else {
      state.conversation.forEach(function (turn) {
        var div = el("div", "bubble " + turn.role);
        div.appendChild(el("b", null, turn.role === "user" ? "você: " : "jarvis: "));
        div.appendChild(document.createTextNode(turn.text));
        conversation.appendChild(div);
      });
    }

    fill("timeline", state.timeline, function (entry) {
      return line(entry.summary || entry.event_type, time(entry.recorded_at),
                  "sev-" + entry.severity);
    });
    fill("context", state.context, function (row) {
      var li = line(row.field + ": " + row.value, row.freshness || "");
      li.appendChild(el("div", "tag", row.source || ""));
      return li;
    });
    fill("memories", state.memories, function (card) {
      var li = line(card.content, card.score !== null && card.score !== undefined
        ? "score " + card.score.toFixed(2) : card.type);
      li.appendChild(el("div", "tag",
        "imp " + card.importance.toFixed(2) + " · conf " + card.confidence.toFixed(2) +
        " · " + card.origin + (card.used_in_turn ? " · usada neste turno" : "")));
      return li;
    });
    fill("decisions", state.decisions, function (card) {
      var li = line(card.decision_type + (card.message ? " — " + card.message : ""),
                    time(card.decided_at));
      if (card.reason) { li.appendChild(el("div", "tag", card.reason)); }
      return li;
    });
    fill("actions", state.actions, function (card) {
      var li = line(card.skill + " · " + (card.status || "?"), time(card.at),
                    card.status === "failed" ? "sev-danger" : "");
      li.appendChild(el("div", "tag",
        (card.verdict ? "política " + card.verdict : "") +
        (card.rule_id ? " (" + card.rule_id + ")" : "") +
        (card.duration_ms ? " · " + card.duration_ms.toFixed(0) + " ms" : "")));
      return li;
    });
    fill("tools", state.tools, function (card) {
      return line(card.tool_id + " · " + card.status, time(card.at),
                  card.status === "failed" ? "sev-danger" : "");
    });

    (state.toasts || []).forEach(function (toast) {
      if (seenToasts.has(toast.toast_id)) { return; }
      seenToasts.add(toast.toast_id);
      var node = el("div", "toast sev-" + toast.severity);
      node.appendChild(el("strong", null, toast.title));
      node.appendChild(el("span", null, toast.body));
      document.getElementById("toasts").appendChild(node);
      setTimeout(function () { node.remove(); }, 8000);
    });
  }

  function poll() {
    fetch("/api/state").then(function (response) { return response.json(); })
      .then(render).catch(function () {});
  }

  function connect() {
    var source = new EventSource("/api/stream");
    source.onmessage = function (message) { render(JSON.parse(message.data)); };
    source.onerror = function () {
      source.close();
      failures += 1;
      // Duas falhas bastam para desistir do stream: um painel local que fica
      // tentando reconectar sozinho vira suporte técnico.
      if (failures >= 2) { setInterval(poll, 3000); poll(); }
      else { setTimeout(connect, 1500); }
    };
  }

  poll();
  connect();
})();
</script>
</body>
</html>
"""
