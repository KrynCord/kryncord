"""Cargos de servidor — criação, edição, e o vínculo com membros.

O Discord não tem "cargo em uso" separado: `DELETE /guilds/:id/roles/:id`
apaga o cargo e **remove de todo mundo** que o tem, de uma vez, sem
confirmação. Não há desfazer. É o endpoint mais destrutivo que existe
num servidor de 10 mil membros, e por isso `delete` está aqui sem nenhum
atalho — quem chama é quem sabe.

Adicionar e remover cargo de membro são `PUT`/`DELETE` sobre
``/members/:id/roles/:role``, que é o caminho para autorole e para
cargos por reação — e ambos **ignoram o cargo @everyone**, que o Discord
não deixa dar nem tirar por essa rota.
"""

from __future__ import annotations

import builtins
from typing import Any

from kryncord.api._parse import expect_list, expect_model
from kryncord.models.role import Role
from kryncord.rest.client import RESTClient


class RolesAPI:
    """Operações de cargo."""

    __slots__ = ("_rest",)

    def __init__(self, rest: RESTClient) -> None:
        self._rest = rest

    async def list(self, guild_id: int | str) -> builtins.list[Role]:
        """Todos os cargos da guild.

        Não pagina — o Discord devolve a lista inteira de uma vez, e é
        a única listagem de guild que faz assim. Paginaria por nada.

        `builtins.list` e não `list`: este método sombreia o builtin
        dentro do corpo da classe, e uma anotação ``list[...]`` escrita
        depois dele resolveria para o método.
        """
        return expect_list(
            Role,
            await self._rest.request("GET", f"/guilds/{guild_id}/roles"),
            route="GET /guilds/:id/roles",
        )

    async def fetch(self, guild_id: int | str, role_id: int | str) -> Role:
        """Busca um cargo específico."""
        return expect_model(
            Role,
            await self._rest.request("GET", f"/guilds/{guild_id}/roles/{role_id}"),
            route="GET /guilds/:id/roles/:id",
        )

    async def create(self, guild_id: int | str, name: str, **fields: Any) -> Role:
        """Cria um cargo. `fields` é o corpo direto do Discord.

        ``color`` é int de 24 bits (``0xFF0000`` é vermelho), ``hoist``
        separa o membro do resto da lista, ``permissions`` é string de
        bits — o mesmo formato que `Role.permissions`.
        """
        return expect_model(
            Role,
            await self._rest.request(
                "POST",
                f"/guilds/{guild_id}/roles",
                json={"name": name, **fields},
            ),
            route="POST /guilds/:id/roles",
        )

    async def edit(self, guild_id: int | str, role_id: int | str, **fields: Any) -> Role:
        """Altera um cargo. Só os campos enviados mudam.

        O Discord faz merge, não substituição — mandar só ``name`` não
        zera a cor nem as permissões.
        """
        return expect_model(
            Role,
            await self._rest.request(
                "PATCH",
                f"/guilds/{guild_id}/roles/{role_id}",
                json=fields,
            ),
            route="PATCH /guilds/:id/roles/:id",
        )

    async def delete(self, guild_id: int | str, role_id: int | str) -> None:
        """Apaga um cargo **e remove de todos os membros** de uma vez.

        Devolve 204, sem corpo. Não há desfazer, nem confirmação, nem
        undo — é uma ação irreversível por design do Discord.
        """
        await self._rest.request("DELETE", f"/guilds/{guild_id}/roles/{role_id}")

    async def add_to_member(
        self, guild_id: int | str, user_id: int | str, role_id: int | str
    ) -> None:
        """Dá um cargo a um membro. Devolve 204, sem corpo.

        Requer permissão ``MANAGE_ROLES`` e um cargo **abaixo** do do
        bot na hierarquia — senão o Discord devolve 403, e a mensagem
        aponta a hierarquia, não a permissão.
        """
        await self._rest.request("PUT", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}")

    async def remove_from_member(
        self, guild_id: int | str, user_id: int | str, role_id: int | str
    ) -> None:
        """Tira um cargo de um membro. Devolve 204, sem corpo.

        Ignora o @everyone — o Discord não deixa removê-lo por aqui.
        """
        await self._rest.request("DELETE", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}")
