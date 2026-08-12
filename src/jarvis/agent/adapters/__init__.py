"""Adapters de Infrastructure do Agent Runtime.

Nada aqui é importado pelo Core: o composition root (`jarvis.cli`) escolhe a
implementação concreta e a injeta. Trocar de fornecedor de LLM é escrever um
módulo novo neste pacote e mudar uma linha de wiring — nenhuma alteração em
`runtime.py`, `prompt.py`, `decision.py` ou nas Skills futuras
([ADR-0002](../../../../docs/adr/0002-llm-provider-abstraction.md)).
"""
