"""Adapters da camada de Tools.

Implementações concretas de `ToolBackend`. Só o composition root (`cli.py`) as
importa — nenhum módulo de Core alcança este pacote, e é aqui que moram as
únicas dependências de `pathlib`, `platform` e `subprocess` da camada de ação.
"""
