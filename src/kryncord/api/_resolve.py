"""Aceitar ID **ou** objeto nas chamadas de API.

A pergunta que este módulo resolve: quando alguém escreve
``api.messages.send(canal, "oi")``, o que ``canal`` pode ser?

A resposta é quase tudo — ``123``, ``"123"``, um `Channel`, um
`PartialChannel`, ou a própria `Message` (que carrega o ``channel_id``).
Aceitar as cinco formas custa dez linhas e evita que o chamador decore
qual método quer int e qual quer objeto.

O modelo continua sendo dado puro. Nada aqui injeta cliente em modelo —
ver `api/__init__.py` para a razão.
"""

from __future__ import annotations

from typing import TypeAlias

from kryncord.models.channel import Channel
from kryncord.models.message import Message
from kryncord.models.partial import PartialChannel, PartialMessage

#: Qualquer coisa que identifica um canal.
ChannelLike: TypeAlias = int | str | Channel | PartialChannel | Message | PartialMessage

#: Qualquer coisa que identifica uma mensagem.
MessageLike: TypeAlias = int | str | Message | PartialMessage


def channel_id_of(value: ChannelLike) -> int:
    """ID do canal, seja qual for a forma recebida.

    De um `Message` pega o ``channel_id`` — é o caminho que faz
    ``send(mensagem.channel, ...)`` funcionar sem o chamador ter que
    saber que aquele campo existe.
    """
    if isinstance(value, (Message, PartialMessage)):
        return value.channel_id
    if isinstance(value, (Channel, PartialChannel)):
        return value.id
    return _as_id(value, "canal")


def message_id_of(value: MessageLike) -> int:
    """ID da mensagem, seja qual for a forma recebida."""
    if isinstance(value, (Message, PartialMessage)):
        return value.id
    return _as_id(value, "mensagem")


def _as_id(value: object, o_que: str) -> int:
    """Converte o que for ID em ``int``.

    `bool` é barrado antes de chegar em `int`: ``True == 1`` em Python,
    e um ``True`` passaria como se fosse o canal de ID 1.
    """
    if isinstance(value, bool):
        raise TypeError(f"{o_que} não pode ser bool — recebido {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
        raise ValueError(f"{o_que} numérico esperado, recebido {value!r}")
    raise TypeError(f"{o_que} não identificável: recebido {type(value).__name__} ({value!r})")
