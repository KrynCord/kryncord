"""Mensagem.

O objeto mais usado da biblioteca, e por isso o que mais leva cuidado.
Três decisões valem a pena ler antes de usar:

**`content` é `None`, não `""`.** Mensagem sem texto e mensagem vazia
não são a mesma coisa, e o Discord manda as duas. Um ``if
message.content:`` trata ambas igual e é quase sempre o que se quer —
mas um ``message.content or ""`` mentiria sobre o que veio.

**`author` é `None`, não um usuário vazio.** Mensagens de webhook e de
sistema às vezes vêm sem autor. Inventar um seria fazer o bot falar com
um fantasma.

**`mentions` guarda IDs, não objetos.** Uma mensagem que menciona mil
pessoas não deve custar mil objetos `User` carregados.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kryncord.models.attachment import Attachment
from kryncord.models.base import (
    boolean,
    integer,
    parse_all,
    sequence,
    snowflake,
    string,
    timestamp,
)
from kryncord.models.member import Member
from kryncord.models.user import User

#: Tipo 0 = mensagem padrão. O Discord tem mais de quinze, mas quase
#: todo bot só trata esta — as outras (resposta de comando, thread do
#: sistema) se identificam por ``type``.
DEFAULT_MESSAGE_TYPE = 0


@dataclass(frozen=True, slots=True)
class Message:
    """Uma mensagem recebida pelo Gateway."""

    id: int
    channel_id: int
    guild_id: int | None = None
    author: User | None = None
    member: Member | None = None
    content: str | None = None
    timestamp: datetime | None = None
    edited_at: datetime | None = None
    tts: bool = False
    mention_everyone: bool = False
    mentions: tuple[int, ...] = ()
    mention_roles: tuple[int, ...] = ()
    attachments: tuple[Attachment, ...] = ()
    pinned: bool = False
    type: int | None = None
    webhook_id: int | None = None
    flags: int = 0
    referenced_message: Message | None = None
    interaction_id: int | None = None
    interaction_name: str | None = None
    application_id: int | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> Message | None:
        """Monta a partir do payload cru de um ``MESSAGE_CREATE``/``UPDATE``.

        `author` e `content` ficam `None` quando não vieram — o
        ``MESSAGE_UPDATE`` parcial manda só o que mudou, e um modelo
        que preenche o resto com default faz o handler achar que o
        texto foi apagado quando só não veio.

        `None` (o objeto inteiro) quando falta o ``id``: uma mensagem
        sem ID não é mensagem, e o dispatcher entrega o payload cru
        nesse caso — ver `events/dispatcher.py`.
        """
        message_id = snowflake(data, "id")
        if message_id is None:
            return None
        author_payload = data.get("author")
        member_payload = data.get("member")
        reference = data.get("referenced_message")
        return cls(
            id=message_id,
            channel_id=snowflake(data, "channel_id") or 0,
            guild_id=snowflake(data, "guild_id"),
            author=User.from_payload(author_payload)
            if isinstance(author_payload, Mapping)
            else None,
            member=Member.from_payload(member_payload)
            if isinstance(member_payload, Mapping)
            else None,
            content=string(data, "content"),
            timestamp=timestamp(data, "timestamp"),
            edited_at=timestamp(data, "edited_timestamp"),
            tts=boolean(data, "tts"),
            mention_everyone=boolean(data, "mention_everyone"),
            mentions=_ids_of(data, "mentions"),
            mention_roles=_ids_of(data, "mention_roles"),
            attachments=parse_all(data, "attachments", Attachment.from_payload),
            pinned=boolean(data, "pinned"),
            type=integer(data, "type"),
            webhook_id=snowflake(data, "webhook_id"),
            flags=integer(data, "flags") or 0,
            referenced_message=cls.from_payload(reference)
            if isinstance(reference, Mapping)
            else None,
            interaction_id=snowflake(mapping_of(data, "interaction"), "id"),
            interaction_name=string(mapping_of(data, "interaction"), "name"),
            application_id=snowflake(data, "application_id"),
        )

    # ------------------------------------------------------------------
    # Conveniências
    # ------------------------------------------------------------------

    @property
    def is_default(self) -> bool:
        """Se é uma mensagem comum (não de sistema, não de comando).

        O tipo ``0`` é o que um bot de chat trata; as respostas de
        slash command vêm como ``20`` e quase sempre querem outra
        resposta.
        """
        return self.type == DEFAULT_MESSAGE_TYPE

    @property
    def is_system(self) -> bool:
        """Se é uma mensagem de sistema (entrada no servidor, pin, etc.)."""
        return self.type is not None and self.type != DEFAULT_MESSAGE_TYPE

    @property
    def author_name(self) -> str:
        """Nome de quem escreveu, com fallback seguro.

        `author` é `None` em mensagens de webhook sem autor. Devolver
        ``"?"`` é melhor que levantar ``AttributeError`` no meio de um
        log.
        """
        return self.author.display_name if self.author else "?"

    # Sem `clean_content`: trocar ``<@123>`` por ``@123`` não ajuda, e
    # trocar por nome exige resolver o ID — que é trabalho do cache,
    # ainda não existente. Propriedade que parece ajudar e não ajuda é
    # pior que propriedade ausente.


def _ids_of(data: Mapping[str, Any], key: str) -> tuple[int, ...]:
    """IDs de uma lista que pode trazer tanto string quanto objeto.

    ``mentions`` vem como lista de objetos `User`; ``mention_roles``
    vem como lista de strings de ID. As duas coisas respondem pelo
    mesmo ``id``, e ambas viram ``int`` — comparar ``"123" == 123``
    falha em silêncio.
    """
    ids: list[int] = []
    for item in sequence(data, key):
        if isinstance(item, Mapping):
            found = snowflake(item, "id")
            if found is not None:
                ids.append(found)
        elif isinstance(item, str) and item.isdigit():
            ids.append(int(item))
    return tuple(ids)


def mapping_of(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Lê um objeto aninhado, devolvendo vazio se não for objeto."""
    value = data.get(key)
    return value if isinstance(value, Mapping) else {}
