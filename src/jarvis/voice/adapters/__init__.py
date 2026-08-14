"""Adapters de Infrastructure da camada de voz.

Só o composition root (`cli.py`) importa deste subpacote — um teste arquitetural
garante isso. Cada módulo aqui implementa um port de `voice/ports.py` e é o único
lugar que conhece a tecnologia correspondente: `sounddevice` para dispositivo,
REST da Groq para transcrição, REST do Google Cloud para síntese, SQLite para
sessões.
"""
