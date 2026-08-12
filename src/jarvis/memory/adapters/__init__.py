"""Infrastructure do Memory System.

`SqliteMemoryRepository` implementa o port `MemoryRepository`.
`HashingEmbeddingProvider` implementa o port `EmbeddingProvider` com um algoritmo
local e determinístico — similaridade lexical, não semântica; um adapter de
vendor real é escopo de uma fase futura, e não da Fase 4, que manteve este de
propósito (ver o docstring de `hashing_embeddings.py`).
`event_consumer.py` e `context_bridge.py` são adapters de **entrada**: o
Memory Core não conhece o Event System nem o Context Engine (contracts §3.3).
"""
