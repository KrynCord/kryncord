"""Nomes de evento, em duas formas que convivem.

O Discord manda ``MESSAGE_CREATE`` — maiúsculas, underscore, e sem
sentido como identificador de Python. `ideias/10-events.md` decidiu que
a biblioteca usa ``message_create``, em snake_case, e este módulo é a
ponte entre os dois.

As duas formas ficam registradas, e `normalize_event_name` aceita
qualquer uma. Motivo prático: `client.on("READY")` já funciona e está
em uso; trocar o nome de uma hora para outra é como se quebra
compatibilidade sem ganhar nada. Quem preferir o snake_case pode
usar — os dois chegam ao mesmo handler.
"""

from __future__ import annotations

from enum import StrEnum


class EventName(StrEnum):
    """Nomes de evento que a biblioteca sabe interpretar.

    Só os que têm parser em `events/dispatcher.py`. Eventos que o
    Discord manda e não estão aqui chegam crus ao handler — a
    biblioteca não finge que entende o que ainda não interpretou.
    """

    READY = "ready"
    RESUMED = "resumed"

    MESSAGE_CREATE = "message_create"
    MESSAGE_UPDATE = "message_update"
    MESSAGE_DELETE = "message_delete"
    MESSAGE_DELETE_BULK = "message_delete_bulk"

    GUILD_CREATE = "guild_create"
    GUILD_UPDATE = "guild_update"
    GUILD_DELETE = "guild_delete"

    CHANNEL_CREATE = "channel_create"
    CHANNEL_UPDATE = "channel_update"
    CHANNEL_DELETE = "channel_delete"

    INTERACTION_CREATE = "interaction_create"
    TYPING_START = "typing_start"
    VOICE_STATE_UPDATE = "voice_state_update"


#: Nome do dispatch (como o Discord manda) → nome em snake_case.
RAW_TO_SNAKE: dict[str, str] = {name.name: name.value for name in EventName}


def normalize_event_name(name: str) -> str:
    """Devolve o nome em snake_case, seja qual for a forma recebida.

    ``"MESSAGE_CREATE"``, ``"message_create"`` e
    ``EventName.MESSAGE_CREATE`` produzem o mesmo resultado. Nome
    desconhecido volta como está, em maiúsculas — para o handler de um
    evento que ainda não tem parser continuar funcionando.
    """
    upper = name.upper()
    return RAW_TO_SNAKE.get(upper, upper)
