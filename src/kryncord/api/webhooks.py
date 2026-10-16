"""Webhooks — criação, edição e execução.

Webhook é o endpoint com **dois modos de autenticação** que confundem
quem lê o docs: `GET /webhooks/:id` exige o bot logado e devolve o
webhook **sem token**; `GET /webhooks/:id/:token` devolve **com**. O
token é um segredo — quem o tem executa o webhook sem nenhuma
autenticação —, então o Discord só entrega quando o caminho traz ele.

`execute` por padrão devolve `204`, sem mensagem nenhuma. Quem quer a
mensagem que mandou passa ``wait=True``, que troca o 204 por um 200 com
a `Message` — e paga com mais um ponto de rate limit. Devolver `None`
numa e mensagem noutra é o contrato honesto: o Discord é quem decide.

`execute_url` do modelo nunca pode ir para log. Com o token na mão,
qualquer pessoa manda mensagem no canal do bot.
"""

from __future__ import annotations

import builtins
from typing import Any

from kryncord.api._parse import expect_list, expect_model
from kryncord.http.response import Response
from kryncord.models.message import Message
from kryncord.models.webhook import Webhook
from kryncord.rest.client import RESTClient


class WebhooksAPI:
    """Operações de webhook."""

    __slots__ = ("_rest",)

    def __init__(self, rest: RESTClient) -> None:
        self._rest = rest

    async def list(self, channel_id: int | str) -> builtins.list[Webhook]:
        """Webhooks de um canal, sem os tokens.

        Sem token porque é requisição autenticada normal — o token só
        sai pelo caminho que o traz, e esse exige `MANAGE_WEBHOOKS`.

        `builtins.list` e não `list`: este método sombreia o builtin
        dentro do corpo da classe.
        """
        return expect_list(
            Webhook,
            await self._rest.request("GET", f"/channels/{channel_id}/webhooks"),
            route="GET /channels/:id/webhooks",
        )

    async def fetch(self, webhook_id: int | str, *, token: str | None = None) -> Webhook:
        """Busca um webhook. Com `token`, ele volta junto.

        `token=None` usa o caminho autenticado (sem token no resultado);
        com token, usa o caminho do token — que funciona mesmo sem o bot
        estar logado, se o token for válido.
        """
        if token is None:
            return expect_model(
                Webhook,
                await self._rest.request("GET", f"/webhooks/{webhook_id}"),
                route="GET /webhooks/:id",
            )
        return expect_model(
            Webhook,
            await self._rest.request("GET", f"/webhooks/{webhook_id}/{token}", auth=False),
            route="GET /webhooks/:id/:token",
        )

    async def create(
        self,
        channel_id: int | str,
        name: str,
        *,
        avatar: str | None = None,
        reason: str | None = None,
    ) -> Webhook:
        """Cria um webhook no canal. Devolve **com o token**.

        Este é o único caminho em que o token aparece: `POST` autenticado
        entrega ele uma vez, e depois só pelo caminho do próprio token.
        Se perder aqui, o webhook novo é o caminho honesto.
        """
        fields: dict[str, Any] = {"name": name}
        if avatar is not None:
            fields["avatar"] = avatar
        return expect_model(
            Webhook,
            await self._rest.request(
                "POST",
                f"/channels/{channel_id}/webhooks",
                json=fields,
                reason=reason,
            ),
            route="POST /channels/:id/webhooks",
        )

    async def edit(
        self, webhook_id: int | str, *, token: str | None = None, **fields: Any
    ) -> Webhook:
        """Altera nome, avatar, canal ou configurações de um webhook."""
        response = await self._request("PATCH", webhook_id, token=token, json=fields)
        return expect_model(Webhook, response, route="PATCH /webhooks/:id[/:token]")

    async def delete(
        self,
        webhook_id: int | str,
        *,
        token: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Apaga um webhook. Devolve 204, sem corpo. Não há desfazer."""
        await self._request("DELETE", webhook_id, token=token, reason=reason)

    # ------------------------------------------------------------------
    # Execução
    # ------------------------------------------------------------------

    async def execute(
        self, webhook_id: int | str, token: str, *, wait: bool = False, **payload: Any
    ) -> Message | None:
        """Manda mensagem pelo webhook.

        `wait=False` (padrão) devolve `204` e `None` — não há mensagem
        a devolver, e fingir que há seria inventar um ID. `wait=True`
        troca por `200` com a `Message` real, custando mais um ponto de
        rate limit.

        ``username`` e ``avatar_url`` no `payload` sobrescrevem a
        aparência **só nesta mensagem** — é o "webhook display", não a
        configuração do webhook.
        """
        query = {"wait": "true"} if wait else None
        response = await self._rest.request(
            "POST",
            f"/webhooks/{webhook_id}/{token}",
            json=payload,
            query=query,
            auth=False,
        )
        if not wait:
            return None
        return expect_model(Message, response, route="POST /webhooks/:id/:token?wait=true")

    async def execute_slack(
        self, webhook_id: int | str, token: str, payload: dict[str, Any]
    ) -> None:
        """Executa no formato Slack (`type == 1`).

        Devolve 204 sempre, mesmo com ``?wait=true`` — é a diferença
        que separa este do `execute` de formato Discord.
        """
        await self._rest.request(
            "POST",
            f"/webhooks/{webhook_id}/{token}/slack",
            json=payload,
            auth=False,
        )

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        webhook_id: int | str,
        *,
        token: str | None,
        **kwargs: Any,
    ) -> Response:
        """Monta o caminho com ou sem token.

        Só dois caminhos possíveis, e a diferença é o token na URL —
        `auth=False` quando o token faz autenticação, para não mandar o
        ``Authorization: Bot`` junto com um webhook que não é de bot.
        """
        if token is None:
            return await self._rest.request(method, f"/webhooks/{webhook_id}", **kwargs)
        return await self._rest.request(
            method, f"/webhooks/{webhook_id}/{token}", auth=False, **kwargs
        )
