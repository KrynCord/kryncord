"""Modelos tipados que representam dados da API.

Dataclasses, não Pydantic — ver `docs/decisions/0003-data-models.md`.

Regra central: **campo ausente não é campo com valor default**. A API do
Discord manda payloads parciais o tempo todo (um `GUILD_UPDATE` não traz
todos os campos). `partial.py` existe para representar isso sem fingir
que o objeto está completo.

Cada modelo expõe `from_payload(data)`, que lê o payload cru do
Discord. Parsing é tolerante: tipo errado vira ausência, não exceção —
um payload estranho não pode derrubar o bot.

Existe **um** caso em que `from_payload` devolve `None`: quando falta o
campo sem o qual o objeto não significa nada (o ``id`` de um `Message`).
Object incompleto não seria útil — só faria o handler perseguir um ID
que não existe. O dispatcher entrega o payload cru nesse caso, que é
mais honesto que entregar um objeto de mentira. `Ready` é a exceção
documentada: é anúncio de sessão, não entidade, e continua útil sem
``session_id``.
"""

from kryncord.models.attachment import Attachment
from kryncord.models.ban import Ban
from kryncord.models.base import (
    CDN_BASE,
    DISCORD_EPOCH_MS,
    boolean,
    cdn,
    default_avatar_url,
    integer,
    mapping,
    parse_all,
    sequence,
    snowflake,
    snowflake_datetime,
    string,
    timestamp,
)
from kryncord.models.channel import Channel
from kryncord.models.command import ApplicationCommand
from kryncord.models.guild import Guild
from kryncord.models.interaction import Interaction
from kryncord.models.member import Member
from kryncord.models.message import DEFAULT_MESSAGE_TYPE, Message
from kryncord.models.partial import PartialChannel, PartialGuild, PartialMessage
from kryncord.models.ready import Ready
from kryncord.models.role import Role
from kryncord.models.typing import TypingStart
from kryncord.models.user import User
from kryncord.models.voice import VoiceState
from kryncord.models.webhook import Webhook

__all__ = [
    "CDN_BASE",
    "DEFAULT_MESSAGE_TYPE",
    "DISCORD_EPOCH_MS",
    "ApplicationCommand",
    "Attachment",
    "Ban",
    "Channel",
    "Guild",
    "Interaction",
    "Member",
    "Message",
    "PartialChannel",
    "PartialGuild",
    "PartialMessage",
    "Ready",
    "Role",
    "TypingStart",
    "User",
    "VoiceState",
    "Webhook",
    "boolean",
    "cdn",
    "default_avatar_url",
    "integer",
    "mapping",
    "parse_all",
    "sequence",
    "snowflake",
    "snowflake_datetime",
    "string",
    "timestamp",
]
