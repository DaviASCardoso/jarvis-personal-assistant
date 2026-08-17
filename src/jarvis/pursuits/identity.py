"""Identidade de um pursuit: sempre aleatória — mesmo critério de
`tasks/identity.py`. Um `agent pursue` novo é sempre uma intenção nova de
quem o pediu, nunca a reapresentação de um objetivo já visto."""

import uuid


def new_pursuit_id() -> str:
    return str(uuid.uuid4())
