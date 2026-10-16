"""Canais e threads.

O Discord não tem "canal". Tem dezenove tipos com comportamentos
diferentes empilhados na mesma tabela, e um bot que só trata
``type == 0`` vai quebrar no primeiro fórum. `ChannelType` existe para
que ninguém precise decorar esses números.

Threads são canais: o ``11`` aqui é um canal com um campo extra, não um
objeto à parte. `Channel.is_thread` é a pergunta certa, não a classe.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kryncord.models.base import (
    boolean,
    integer,
    mapping,
    sequence,
    snowflake,
    string,
    timestamp,
)


@dataclass(frozen=True, slots=True)
class Channel:
    """Um canal de texto, voz, categoria, fórum ou thread.

    Campos que só existem em certos tipos ficam em `None` — o
    ``rate_limit_per_user`` de uma categoria não é "zero lentidão",
    é ausente. `models/base.py` trata ausência como `None` por
    isso.
    """

    id: int
    #: Tipo do canal. Ausente no payload vira ``0`` (texto de guild),
    #: porque é a suposição segura para "dá para enviar aqui?" — um
    #: `Channel` sem tipo não classifica, e não classificar paralisa o
    #: handler que só queria mandar uma mensagem.
    type: int = 0
    guild_id: int | None = None
    name: str | None = None
    position: int | None = None
    parent_id: int | None = None
    topic: str | None = None
    nsfw: bool = False
    last_message_id: int | None = None
    rate_limit_per_user: int | None = None
    owner_id: int | None = None
    recipient_ids: tuple[int, ...] = ()
    message_count: int | None = None
    member_count: int | None = None
    archived: bool = False
    auto_archive_duration: int | None = None
    archive_timestamp: datetime | None = None
    locked: bool = False
    invitable: bool = False
    created_at: datetime | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> Channel | None:
        """Monta a partir do payload cru.

        Exige ``id``: sem ele não há canal identificável, e um `Channel`
        sem ID não dá para enviar nada nele. Devolve `None` quando falta
        — o dispatcher entrega o payload cru nesse caso, que é mais
        honesto que entregar um objeto inútil.
        """
        channel_id = snowflake(data, "id")
        if channel_id is None:
            return None
        thread = mapping(data, "thread_metadata")
        return cls(
            id=channel_id,
            type=integer(data, "type") or 0,
            guild_id=snowflake(data, "guild_id"),
            name=string(data, "name"),
            position=integer(data, "position"),
            parent_id=snowflake(data, "parent_id"),
            topic=string(data, "topic"),
            nsfw=boolean(data, "nsfw"),
            last_message_id=snowflake(data, "last_message_id"),
            rate_limit_per_user=integer(data, "rate_limit_per_user"),
            owner_id=snowflake(data, "owner_id"),
            recipient_ids=_recipient_ids(data),
            message_count=integer(data, "message_count"),
            member_count=integer(data, "member_count"),
            archived=boolean(thread, "archived"),
            auto_archive_duration=integer(thread, "auto_archive_duration"),
            archive_timestamp=timestamp(thread, "archive_timestamp"),
            locked=boolean(thread, "locked"),
            invitable=boolean(thread, "invitable"),
            created_at=timestamp(data, "created_at"),
        )

    # ------------------------------------------------------------------
    # Classificação
    # ------------------------------------------------------------------

    @property
    def is_text(self) -> bool:
        """Texto de guild ou anúncio — onde um bot de comando mora."""
        return self.type in (0, 5)

    @property
    def is_dm(self) -> bool:
        """Conversa direta ou de grupo. Não tem ``guild_id``."""
        return self.type in (1, 3)

    @property
    def is_voice(self) -> bool:
        """Voz de guild ou palco."""
        return self.type in (2, 13)

    @property
    def is_category(self) -> bool:
        """Categoria — agrupador, não envia mensagem."""
        return self.type == 4

    @property
    def is_thread(self) -> bool:
        """Thread pública, privada ou de anúncio.

        É a checagem que importa: threads têm regras próprias de envio,
        e tratar um ``11`` como canal de texto normal é como se ganha
        403 no primeiro ``send``.
        """
        return self.type in (10, 11, 12)

    @property
    def is_sendable(self) -> bool:
        """Se dá para mandar mensagem nele.

        Categoria e canal de voz (sem palco) não aceitam texto. É a
        pergunta que um handler quer antes de ``send``, não a de tipo.
        """
        return self.is_text or self.is_thread or self.is_dm

    @property
    def mention(self) -> str:
        """Texto que menciona o canal no chat."""
        return f"<#{self.id}>"


def _recipient_ids(data: Mapping[str, Any]) -> tuple[int, ...]:
    """IDs de quem participa de uma DM ou grupo.

    O Discord manda objetos `User` inteiros aqui, não IDs. Guardar os
    IDs (e não os objetos) mantém o modelo leve e evita duplicar
    `User` dentro de `Channel` — quem precisa do perfil busca pelo ID.
    """
    ids: list[int] = []
    for recipient in sequence(data, "recipients"):
        if isinstance(recipient, Mapping):
            found = snowflake(recipient, "id")
            if found is not None:
                ids.append(found)
    return tuple(ids)
