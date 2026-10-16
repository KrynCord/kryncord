"""Usuários: quem somos, e quem é alguém.

`me()` é o teste de token mais barato que existe — uma requisição, um
`User` de volta, e o 401 se o token estiver errado. `Client.start()`
valida o formato do token antes de conectar, mas só o Discord diz se ele
ainda é válido.
"""

from __future__ import annotations

from kryncord.api._parse import expect_model
from kryncord.models.user import User
from kryncord.rest.client import RESTClient


class UsersAPI:
    """Operações de usuário."""

    __slots__ = ("_rest",)

    def __init__(self, rest: RESTClient) -> None:
        self._rest = rest

    async def me(self) -> User:
        """``GET /users/@me`` — a conta do bot.

        Bom teste de token: passa, o token é válido; falha com 401, ou
        foi revogado, ou é de outro aplicativo.
        """
        return expect_model(
            User,
            await self._rest.request("GET", "/users/@me"),
            route="GET /users/@me",
        )

    async def fetch(self, user_id: int | str) -> User:
        """Busca um usuário pelo ID.

        Pode devolver um perfil mais enxuto que o do próprio bot — o
        Discord limita o que um bot vê de contas que não estão no mesmo
        servidor.
        """
        return expect_model(
            User,
            await self._rest.request("GET", f"/users/{user_id}"),
            route="GET /users/:id",
        )
