"""Estado de voz de um usuário — o objeto por trás de ``VOICE_STATE_UPDATE``.

Ele é a razão de o cache de voz existir (`0025` §6): sem guardar o
estado anterior, `voice_state_update -> (old, new)` entregaria
`old=None` **sempre**, dentro de uma assinatura que promete
`VoiceState | None`. Quem escreve "saiu do canal de voz" precisa ver o
canal de antes.

Duas peculiaridades do payload:

- ``channel_id`` é ``null`` quando o usuário **saiu** da voz. Não é
  ausência de dado — é o dado. `in_voice` é a pergunta certa.
- ``user_id`` pode vir só dentro do ``member``, e é o caso do
  ``GUILD_CREATE`` (que traz a lista de estados já semeados). Sem
  identificar de quem é, o estado não pode ser guardado nem consultado,
  então `from_payload` devolve `None` — a regra do `0003`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kryncord.models.base import boolean, integer, snowflake, string, timestamp
from kryncord.models.member import Member


@dataclass(frozen=True, slots=True)
class VoiceState:
    """Onde um usuário está na voz, e com que mudo."""

    user_id: int
    channel_id: int | None
    session_id: str | None = None
    guild_id: int | None = None
    member: Member | None = None
    deaf: bool = False
    mute: bool = False
    self_deaf: bool = False
    self_mute: bool = False
    self_stream: bool = False
    self_video: bool = False
    suppress: bool = False
    request_to_speak_timestamp: datetime | None = None
    flags: int = 0

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> VoiceState | None:
        """`None` quando não dá para saber **de quem** é o estado.

        O ``user_id`` vem direto ou do ``member.user.id``. Sem nenhum
        dos dois o objeto não tem dono — guardá-lo criaria uma entrada
        que ninguém consegue consultar nem remover.
        """
        member_payload = data.get("member")
        member = (
            Member.from_payload(member_payload) if isinstance(member_payload, Mapping) else None
        )

        user_id = snowflake(data, "user_id")
        if user_id is None and member is not None:
            user_id = member.user.id
        if user_id is None:
            return None

        return cls(
            user_id=user_id,
            channel_id=snowflake(data, "channel_id"),
            session_id=string(data, "session_id"),
            guild_id=snowflake(data, "guild_id"),
            member=member,
            deaf=boolean(data, "deaf"),
            mute=boolean(data, "mute"),
            self_deaf=boolean(data, "self_deaf"),
            self_mute=boolean(data, "self_mute"),
            self_stream=boolean(data, "self_stream"),
            self_video=boolean(data, "self_video"),
            suppress=boolean(data, "suppress"),
            request_to_speak_timestamp=timestamp(data, "request_to_speak_timestamp"),
            flags=integer(data, "flags") or 0,
        )

    @property
    def in_voice(self) -> bool:
        """`True` se está num canal de voz. `False` = saiu da voz.

        A pergunta certa para ``channel_id == None``, que é **dado** e
        não ausência (`0025` §6).
        """
        return self.channel_id is not None

    @property
    def is_muted(self) -> bool:
        """Mudo de servidor **ou** de si mesmo.

        São dois campos no payload porque fazem coisas diferentes (um é
        mutado pela guild, outro se mutou), mas quem escreve "está
        calado?" não quer decidir qual dos dois perguntar.
        """
        return self.mute or self.self_mute

    @property
    def is_speaking(self) -> bool:
        """Em canal e não self-muteado.

        Não é o ``speaking`` do Voice Gateway (que vem por outro canal,
        o de UDP) — é a leitura do estado que o payload permite.
        """
        return self.in_voice and not self.self_mute
