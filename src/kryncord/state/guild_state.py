"""Visão de um servidor dentro do cache: membros, cargos e canais.

`GuildState` é **leitura**, não uma segunda cópia dos dados. Ele aponta
para o mesmo `CacheProtocol` que o `ConnectionState`, com a guild já
resolvida — existe para que

    client.cache.guild(guild_id).members

seja uma chamada, e não uma varredura com `guild_id` repassado em cada
linha. Não tem estado próprio: dois objetos `GuildState` da mesma guild
vêem as mesmas coisas, e não têm o que divergir.

## Por que fica separado do `ConnectionState`

Porque os dois respondem perguntas diferentes:

- `connection_state` — *o que existe em geral*: `get_channel(id)` é
  global, porque canal tem ID global no Discord e ninguém quer perguntar
  "de qual guild?" antes de ver se tem;
- `guild_state` — *o que existe aqui dentro*: `members`, `roles`,
  `channels` só fazem sentido escopados, porque são justamente os
  itens que só existem dentro de um servidor.

Juntar os dois no mesmo objeto daria um com dois nomes para a mesma
coisa (`members(gid)` e `guild(gid).members`), e a divergência entre
elas seria um bug esperando acontecer.

## `get_channel` verifica a guild

`cache.get_channel(id)` não pergunta de onde veio — é global, e é o
certo. Já `guild_state.get_channel(id)` promete canal *desta* guild, e
se devolvesse um canal de outro servidor a promessa seria mentira. Por
isso ele confere, e devolve `None` para canal de guild alheia: é a
resposta honesta para "este canal está aqui?", não um "não achei" que
esconderia que ele existe, só não aqui.
"""

from __future__ import annotations

from kryncord.cache.keys import CacheKind, channel_key, guild_key, member_key, role_key
from kryncord.cache.protocol import CacheProtocol
from kryncord.models.channel import Channel
from kryncord.models.guild import Guild
from kryncord.models.member import Member
from kryncord.models.role import Role


class GuildState:
    """Leitura do cache escopada numa guild."""

    __slots__ = ("_cache", "_guild_id")

    def __init__(self, cache: CacheProtocol, guild_id: int) -> None:
        self._cache = cache
        self._guild_id = guild_id

    @property
    def id(self) -> int:
        """A guild que esta visão cobre."""
        return self._guild_id

    # ------------------------------------------------------------------
    # Entidades
    # ------------------------------------------------------------------

    @property
    def guild(self) -> Guild | None:
        """O servidor, ou `None` se não está cacheado.

        `None` é o caso normal em quem acabou de conectar: o `READY`
        manda só ``id`` e ``unavailable``, e o objeto completo chega no
        `GUILD_CREATE` logo depois.
        """
        return self._cache.get(CacheKind.GUILD, guild_key(self._guild_id))

    @property
    def members(self) -> tuple[Member, ...]:
        """Membros desta guild que estão no cache.

        **Não é a lista de membros do servidor.** Se a política
        desligou `members`, ou o gateway ainda não entregou todos, aqui
        vem menos — ou nada. A arquitetura proíbe assumir completidão, e
        é nenhuma propriedade mais que esta.
        """
        return self._cache.group_values(CacheKind.MEMBER, str(self._guild_id))

    @property
    def roles(self) -> tuple[Role, ...]:
        """Cargos desta guild que estão no cache."""
        return self._cache.group_values(CacheKind.ROLE, str(self._guild_id))

    @property
    def channels(self) -> tuple[Channel, ...]:
        """Canais desta guild que estão no cache.

        Canais de DM não aparecem: eles não têm guild, e o agrupamento
        deles é `None`. `connection_state.channels` tem todos.
        """
        return self._cache.group_values(CacheKind.CHANNEL, str(self._guild_id))

    # ------------------------------------------------------------------
    # Ponto
    # ------------------------------------------------------------------

    def get_member(self, user_id: int | str) -> Member | None:
        """Um membro desta guild, ou `None`.

        O caminho mais usado do cache — "quem mandou esta mensagem?" —
        e um lookup direto, não uma varredura em `members`.
        """
        return self._cache.get(CacheKind.MEMBER, member_key(self._guild_id, user_id))

    def get_role(self, role_id: int | str) -> Role | None:
        """Um cargo desta guild, ou `None`."""
        return self._cache.get(CacheKind.ROLE, role_key(self._guild_id, role_id))

    def get_channel(self, channel_id: int | str) -> Channel | None:
        """Um canal **desta** guild, ou `None`.

        Diferente de `connection_state.get_channel`, este confere a
        origem: o ID é global, então achar um canal não prova que ele é
        desta guild — e devolver o de outra seria responder outra
        pergunta.
        """
        canal: Channel | None = self._cache.get(CacheKind.CHANNEL, channel_key(channel_id))
        if canal is None:
            return None
        if canal.guild_id != self._guild_id:
            return None
        return canal

    def __repr__(self) -> str:
        """A guild coberta — o que alguém quer ver ao inspecionar."""
        return f"{type(self).__name__}(guild_id={self._guild_id})"
