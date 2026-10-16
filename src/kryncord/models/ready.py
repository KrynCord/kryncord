"""Corpo do evento ``READY`` — a sessão estabelecida.

O ``READY`` é o primeiro dispatch que o bot recebe, e o único que não é
sobre um objeto do Discord: é sobre a *sessão* do bot. Três coisas
interessam nele, e as três têm uso imediato:

- ``user`` — quem o bot é. É como se descobre o ID próprio sem
  perguntar à API.
- ``guild_ids`` — os servidores onde o bot está, antes deles chegarem
  um a um no ``GUILD_CREATE``.
- ``session_id`` / ``resume_gateway_url`` — o contrato para reconectar.
  O Gateway consome isso internamente; fica no modelo porque é o mesmo
  payload, e esconder metade dele seria mentir sobre o que veio.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.models.base import parse_all, string
from kryncord.models.partial import PartialGuild
from kryncord.models.user import User


@dataclass(frozen=True, slots=True)
class Ready:
    """Sessão estabelecida, conforme o payload do ``READY``."""

    user: User | None
    session_id: str | None
    resume_gateway_url: str | None
    guilds: tuple[PartialGuild, ...]
    shard: tuple[int, int] | None = None

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> Ready:
        """Monta a partir do corpo do ``READY``.

        Nenhum campo é obrigatório aqui: o Gateway já validou o
        ``session_id`` antes de entregar o payload, e este modelo é
        para o código da aplicação, não para a máquina de estados.

        `Ready` é a exceção documentada ao contrato de devolver `None`
        quando falta o ID — é anúncio de sessão, não entidade, e
        continua útil sem ``session_id``.
        """
        user_payload = data.get("user")
        return cls(
            user=User.from_payload(user_payload) if isinstance(user_payload, Mapping) else None,
            session_id=string(data, "session_id"),
            resume_gateway_url=string(data, "resume_gateway_url"),
            guilds=parse_all(data, "guilds", PartialGuild.from_payload),
            shard=_shard_pair(data),
        )

    @property
    def guild_ids(self) -> tuple[int, ...]:
        """IDs dos servidores reportados no ``READY``.

        São referências, não guilds carregadas — a guild completa chega
        no ``GUILD_CREATE``. Quem quer o nome, procura depois.
        """
        return tuple(guild.id for guild in self.guilds)

    @property
    def shard_id(self) -> int | None:
        """Índice desta shard, ou `None` se não for shardada."""
        return self.shard[0] if self.shard else None

    @property
    def shard_count(self) -> int | None:
        """Total de shards, ou `None` se não for shardada."""
        return self.shard[1] if self.shard else None


def _shard_pair(data: Mapping[str, Any]) -> tuple[int, int] | None:
    """Lê ``shard: [índice, total]``, ou `None` se vier malformado.

    O Discord manda isso só quando o bot é shardado. Um bot
    não-shardado não tem o campo, e um payload com ``shard: "x"`` é
    anomalia — `None` é melhor que levantar no meio do dispatch.
    """
    shard = data.get("shard")
    if not isinstance(shard, (list, tuple)) or len(shard) < 2:
        return None
    first, second = shard[0], shard[1]
    if isinstance(first, bool) or isinstance(second, bool):
        return None
    if not isinstance(first, int) or not isinstance(second, int):
        return None
    return (first, second)
