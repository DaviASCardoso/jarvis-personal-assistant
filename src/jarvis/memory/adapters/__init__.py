"""Infrastructure do Memory System.

`SqliteMemoryRepository` implementa o port `MemoryRepository`.
`HashingEmbeddingProvider` implementa o port `EmbeddingProvider` com um algoritmo
local e determinístico — similaridade lexical, não semântica; um adapter de
vendor real é escopo da Fase 4, quando houver credenciais e configuração para
ele. `event_consumer.py` e `context_bridge.py` são adapters de **entrada**: o
Memory Core não conhece o Event System nem o Context Engine (contracts §3.3).
"""
