"""Gateway: as informações que decidem quantas shards o bot precisa.

`bot()` é a única rota aqui — mas o vocabulário importa: perguntar
`client.api.gateway.bot()` é perguntar ao Discord "quantas shards, e
quanto cabe de identify ainda", que é a pergunta de todo bot que
cresceu além de uma.

O `session_start_limit` envelhece a cada identify, então os dados são
frescos só na hora: quem decide sharding com isto busca **antes de
conectar**, como o discord.js faz (o `WebSocketManager` busca o
`/gateway/bot` logo antes do spawn, e não no boot).
"""

from __future__ import annotations

from kryncord.api._parse import expect_model
from kryncord.models.gateway import GatewayBotInfo
from kryncord.rest.client import RESTClient


class GatewayAPI:
    """Operações REST da camada Gateway."""

    __slots__ = ("_rest",)

    def __init__(self, rest: RESTClient) -> None:
        self._rest = rest

    async def bot(self) -> GatewayBotInfo:
        """``GET /gateway/bot`` — shards sugeridas e teto de identifies.

        O número que importa é `session_start_limit.remaining`: é o
        quantos identifies ainda cabem, e conectar `n` shards consome
        `n`. Esgotou, a espera é `reset_after` segundos — e dizer isso
        na mensagem de erro é mais útil que dizer "limite estourado".
        """
        return expect_model(
            GatewayBotInfo,
            await self._rest.request("GET", "/gateway/bot"),
            route="GET /gateway/bot",
        )
