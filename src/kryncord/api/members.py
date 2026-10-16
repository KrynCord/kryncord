"""Membros de servidor — leitura, entrada, saída, moderação.

`GET /guilds/:id/members` tem um limite que engana: ``limit`` aceita até
**1000**, mas sem ``after`` ele devolve os 1000 primeiros, e para
servidor maior é página de nada. A paginação é por ``after`` com o ID do
membro — monotônico no snowflake, então funciona como cursor.

`kick`, `ban` e `unban` têm algo em comum que nenhum outro endpoint tem:
**devolvem o usuário afetado**. Guardar isso seria jogar fora a prova de
quem saiu — `kick` devolve o `User` que foi kicado.

Razão de moderação (``reason``) vai no parâmetro `reason` de
`RESTClient.request`, não em header montado à mão: é quem cuida do
``X-Audit-Log-Reason`` e do URL-encoding dele. Um motivo com acento feito
à mão daria 400 — e o erro apontaria o header, não o texto.
"""

from __future__ import annotations

import builtins
from typing import Any

from kryncord.api._parse import expect_list, expect_model
from kryncord.models.ban import Ban
from kryncord.models.member import Member
from kryncord.models.user import User
from kryncord.rest.client import RESTClient

#: Tamanho de página que o Discord aceita. 1000 é o máximo, e é o
#: valor que minimiza ida e volta em servidor grande.
DEFAULT_PAGE = 1000


class MembersAPI:
    """Operações de membro."""

    __slots__ = ("_rest",)

    def __init__(self, rest: RESTClient) -> None:
        self._rest = rest

    async def list(
        self,
        guild_id: int | str,
        *,
        limit: int = DEFAULT_PAGE,
        after: int | str | None = None,
    ) -> builtins.list[Member]:
        """Uma página de membros.

        `after` é o cursor: passe o `id` do último membro da página
        anterior. Sem ele, sempre volta a primeira página — servidor
        com 50 mil membros devolve sempre os mesmos 1000.
        """
        return expect_list(
            Member,
            await self._rest.request(
                "GET",
                f"/guilds/{guild_id}/members",
                query=_page(limit, after),
            ),
            route="GET /guilds/:id/members",
        )

    async def fetch(self, guild_id: int | str, user_id: int | str) -> Member:
        """Busca um membro. Falha com 404 se não estiver na guild.

        Para ver alguém que *poderia* estar, `users.fetch` é o certo —
        esse devolve a conta sem perguntar guild nenhuma.
        """
        return expect_model(
            Member,
            await self._rest.request("GET", f"/guilds/{guild_id}/members/{user_id}"),
            route="GET /guilds/:id/members/:id",
        )

    async def add(self, guild_id: int | str, user_id: int | str, **fields: Any) -> Member:
        """Põe um usuário na guild — é o "join automático" de bot.

        ``access_token`` é obrigatório na prática: o token OAuth2 com
        escopo ``guilds.join``. Sem ele o Discord devolve 400 apontando
        o campo. `fields` aceita também ``nick``, ``roles``, ``mute`` e
        ``deaf``.
        """
        return expect_model(
            Member,
            await self._rest.request(
                "PUT",
                f"/guilds/{guild_id}/members/{user_id}",
                json=fields,
            ),
            route="PUT /guilds/:id/members/:id",
        )

    async def edit(self, guild_id: int | str, user_id: int | str, **fields: Any) -> Member:
        """Altera apelido, cargos ou timeout de um membro.

        Os cinco campos que este endpoint aceita são ``nick``,
        ``roles``, ``mute``, ``deaf`` e ``communication_disabled_until``.
        Um campo fora da lista o Discord não valida — ele quebra, com
        500 e mensagem nenhuma. Por isso estão listados em docstring em
        vez de um ``**anything`` silencioso.
        """
        return expect_model(
            Member,
            await self._rest.request(
                "PATCH",
                f"/guilds/{guild_id}/members/{user_id}",
                json=fields,
            ),
            route="PATCH /guilds/:id/members/:id",
        )

    async def remove(
        self, guild_id: int | str, user_id: int | str, *, reason: str | None = None
    ) -> User:
        """Kick — expulsa sem banir. Devolve o `User` que saiu."""
        return expect_model(
            User,
            await self._rest.request(
                "DELETE",
                f"/guilds/{guild_id}/members/{user_id}",
                reason=_reason(reason),
            ),
            route="DELETE /guilds/:id/members/:id",
        )

    async def ban(
        self,
        guild_id: int | str,
        user_id: int | str,
        *,
        delete_message_seconds: int | None = None,
        reason: str | None = None,
    ) -> User:
        """Bane um membro. Devolve o `User` banido.

        ``delete_message_seconds`` apaga as mensagens dele — de 0 a
        604800 (7 dias). O Discord **ignora** o valor acima disso em vez
        de reclamar, então um ``864000`` vira 7 dias sem avisar.
        """
        fields: dict[str, Any] = {}
        if delete_message_seconds is not None:
            fields["delete_message_seconds"] = delete_message_seconds
        return expect_model(
            User,
            await self._rest.request(
                "PUT",
                f"/guilds/{guild_id}/bans/{user_id}",
                json=fields,
                reason=_reason(reason),
            ),
            route="PUT /guilds/:id/bans/:id",
        )

    async def unban(
        self, guild_id: int | str, user_id: int | str, *, reason: str | None = None
    ) -> User:
        """Desbane. Devolve o `User` que voltou a poder entrar."""
        return expect_model(
            User,
            await self._rest.request(
                "DELETE",
                f"/guilds/{guild_id}/bans/{user_id}",
                reason=_reason(reason),
            ),
            route="DELETE /guilds/:id/bans/:id",
        )

    async def bans(
        self,
        guild_id: int | str,
        *,
        limit: int = DEFAULT_PAGE,
        after: int | str | None = None,
    ) -> builtins.list[Ban]:
        """Página de bans, com o motivo de cada um.

        Mesmo cursor de membros: ``after`` com o ID. Sem paginação o
        Discord devolve 1000, e servidor com histórico de moderação
        passa disso rápido.

        `builtins.list` e não `list`: o método `list` desta classe
        sombreia o builtin dentro do corpo dela, e uma anotação
        ``list[...]`` escrita depois dele resolve para o método.
        """
        return expect_list(
            Ban,
            await self._rest.request(
                "GET",
                f"/guilds/{guild_id}/bans",
                query=_page(limit, after),
            ),
            route="GET /guilds/:id/bans",
        )

    async def fetch_ban(self, guild_id: int | str, user_id: int | str) -> Ban:
        """Busca o ban de um usuário — com o motivo.

        404 se não estiver banido, que é a resposta certa para "está
        banido?": não, e o Discord diz com status.
        """
        return expect_model(
            Ban,
            await self._rest.request("GET", f"/guilds/{guild_id}/bans/{user_id}"),
            route="GET /guilds/:id/bans/:id",
        )


def _reason(reason: str | None) -> str | None:
    """Razão de auditoria normalizada: em branco vira `None`.

    ``"   "`` como razão registraria no audit log uma entrada vazia —
    alguém abrindo o histórico leria "por quê?", que é pior que não ter
    registrado. ``None`` não manda o header nenhum.

    Só aqui, e não em `http/client.py`: o transporte manda o que recebe,
    que é o contrato dele. Decidir o que *significa* razão é vocabulário,
    e vocabulário é o trabalho da `api/`.
    """
    if not isinstance(reason, str):
        return None
    return reason.strip() or None


def _page(limit: int, after: int | str | None) -> dict[str, Any]:
    """Query de paginação, omitindo `after` quando não veio.

    ``after=`` vazio e ausente significam a mesma coisa para o Discord,
    mas o segundo não manda parâmetro nenhum — e a URL fica legível.
    """
    query: dict[str, Any] = {"limit": limit}
    if after is not None:
        query["after"] = after
    return query
