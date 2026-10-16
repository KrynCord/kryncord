"""Comandos de aplicação — registro, edição e sincronização.

O detalhe que decide a forma destes métodos: **`guild_id=None` é
global**, e é o mesmo endpoint com um segmento a menos.

    /applications/:id/comandos          → global
    /applications/:id/guilds/:g/comandos → da guild

Uma lista `global_` e outra `guild_` de quase idênticos seria duas
fontes de verdade para a mesma lógica. Aqui é um parâmetro opcional,
que é o que a URL realmente é.

A forma segura de sincronizar é `bulk_overwrite` (``PUT``): substitui a
lista inteira. Criar um a um deixa comandos órfãos quando alguém apaga
um do código — e órfão aparece pro usuário como comando que não faz
nada. É o método que existe para o `main.py` de todo bot.

Comando global leva **até 1 hora** para propagar. Da guild, instantâneo.
Nenhum endpoint acelera isso, e nenhum erro diz "ainda não propagou" —
simplesmente não aparece ainda.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from kryncord.api._parse import expect_list, expect_model
from kryncord.models.command import ApplicationCommand
from kryncord.rest.client import RESTClient


class ApplicationsAPI:
    """Operações de aplicação e de seus comandos."""

    __slots__ = ("_rest",)

    def __init__(self, rest: RESTClient) -> None:
        self._rest = rest

    async def me(self) -> dict[str, Any]:
        """``GET /applications/@me`` — a aplicação logada.

        Devolve dict, não modelo: este payload muda com escopo OAuth2
        (traz ``redirect_uris``, ``team``, ``install_params``…) e
        modelar uma árvore que só existe em app de usuário seria fingir
        cobrir o que não cobrimos. `application_id` está sempre aqui,
        e é o campo que se busca.

        Para bot, ``application_id == user.id`` — mas perguntar ao
        Discord é mais honesto que assumir.
        """
        return dict(await self._rest.request_json("GET", "/applications/@me"))

    async def list_commands(
        self, application_id: int | str, *, guild_id: int | str | None = None
    ) -> list[ApplicationCommand]:
        """Comandos registrados — globais, ou os de `guild_id`."""
        return expect_list(
            ApplicationCommand,
            await self._rest.request("GET", self._commands(application_id, guild_id)),
            route=self._route("GET", guild_id),
        )

    async def fetch_command(
        self,
        application_id: int | str,
        command_id: int | str,
        *,
        guild_id: int | str | None = None,
    ) -> ApplicationCommand:
        """Busca um comando pelo ID."""
        return expect_model(
            ApplicationCommand,
            await self._rest.request(
                "GET", f"{self._commands(application_id, guild_id)}/{command_id}"
            ),
            route=self._route("GET", guild_id) + "/:id",
        )

    async def create_command(
        self,
        application_id: int | str,
        command: Mapping[str, Any],
        *,
        guild_id: int | str | None = None,
    ) -> ApplicationCommand:
        """Cria um comando. `command` é o payload do Discord.

        Os campos mínimos são ``name`` e ``description`` — exceto para
        comando de contexto (tipo 2/3), onde a descrição é obrigatória
        e vazia. `ApplicationCommand.from_payload` trata essa exceção.
        """
        return expect_model(
            ApplicationCommand,
            await self._rest.request(
                "POST",
                self._commands(application_id, guild_id),
                json=dict(command),
            ),
            route=self._route("POST", guild_id),
        )

    async def edit_command(
        self,
        application_id: int | str,
        command_id: int | str,
        *,
        guild_id: int | str | None = None,
        **fields: Any,
    ) -> ApplicationCommand:
        """Altera um comando. Só o que vier muda.

        Mudar ``name`` de um comando global **repropaga do zero** — o
        Discord trata como novo comando para o cliente. Vale a pena
        saber antes de renomear em produção.
        """
        return expect_model(
            ApplicationCommand,
            await self._rest.request(
                "PATCH",
                f"{self._commands(application_id, guild_id)}/{command_id}",
                json=fields,
            ),
            route=self._route("PATCH", guild_id) + "/:id",
        )

    async def delete_command(
        self,
        application_id: int | str,
        command_id: int | str,
        *,
        guild_id: int | str | None = None,
    ) -> None:
        """Apaga um comando. Devolve 204, sem corpo."""
        await self._rest.request(
            "DELETE",
            f"{self._commands(application_id, guild_id)}/{command_id}",
        )

    async def bulk_overwrite_commands(
        self,
        application_id: int | str,
        commands: Iterable[Mapping[str, Any]],
        *,
        guild_id: int | str | None = None,
    ) -> list[ApplicationCommand]:
        """Substitui a lista inteira de comandos de uma vez.

        O método de sincronização. `PUT` apaga tudo que não está na
        lista e cria o que falta — é assim que um bot mantém o
        registro alinhado com o código, sem rastrear o que já existe.

        Para comando **global**, a alteração leva até 1 hora para o
        Discord propagar; da guild, é imediata.
        """
        return expect_list(
            ApplicationCommand,
            await self._rest.request(
                "PUT",
                self._commands(application_id, guild_id),
                json=[dict(c) for c in commands],
            ),
            route=self._route("PUT", guild_id),
        )

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    @staticmethod
    def _commands(application_id: int | str, guild_id: int | str | None) -> str:
        """Caminho dos comandos. `guild_id=None` é o global."""
        base = f"/applications/{application_id}/commands"
        if guild_id is None:
            return base
        return f"/applications/{application_id}/guilds/{guild_id}/commands"

    @staticmethod
    def _route(method: str, guild_id: int | str | None) -> str:
        """Rota na mensagem de erro, para o chamador saber o que falhou."""
        if guild_id is None:
            return f"{method} /applications/:id/commands"
        return f"{method} /applications/:id/guilds/:gid/commands"
