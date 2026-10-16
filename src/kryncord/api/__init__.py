"""Operações REST por recurso do Discord.

Cada módulo organiza chamadas de alto nível de um recurso. Nenhum aqui
duplica lógica de transporte — todos delegam para `rest.client.RESTClient`.

Não confundir com `rest/`: `rest/` é a *mecânica* (rotas, rate limits,
retries), `api/` é o *vocabulário* (o que significa criar um canal).

Uso::

    async with Client(config) as client:
        @client.on("message_create")
        async def responde(message: Message) -> None:
            if message.content == "!ping":
                await client.api.messages.reply(message, "pong")

## Por que `client.api` e não `message.reply()`

É a pergunta que mais aparece, e a resposta é uma decisão, não um
esquecimento. `discord.py` e `discord.js` dão `message.reply()` — o
modelo carrega uma referência ao bot.

Não fazemos isso, e a razão é que **modelos são dados**. Um `Message` é
`frozen=True, slots=True`: não muda, não tem comportamento, e é
construível em um teste com `Message.from_payload({...})` sem existir
nenhum `Client` no processo. Injetar o cliente nele transformaria o
modelo em dependência de estado de runtime, e aí o teste que quer só
verificar parsing teria que construir um bot primeiro.

O custo é uma palavra a mais por chamada — `client.api.messages.reply`
em vez de `message.reply`. O ganho é que o modelo continua sendo o que
a `0003` prometeu: dado puro, imutável, testável sozinho.

`message.reply()` pode vir depois como açúcar por cima disto, sem
quebrar nada — é aditivo.
"""

from __future__ import annotations

from kryncord.api.applications import ApplicationsAPI
from kryncord.api.channels import ChannelsAPI
from kryncord.api.guilds import GuildsAPI
from kryncord.api.interactions import InteractionsAPI
from kryncord.api.members import MembersAPI
from kryncord.api.messages import MessagesAPI
from kryncord.api.roles import RolesAPI
from kryncord.api.users import UsersAPI
from kryncord.api.webhooks import WebhooksAPI
from kryncord.rest.client import RESTClient

__all__ = [
    "ApplicationsAPI",
    "ChannelsAPI",
    "DiscordAPI",
    "GuildsAPI",
    "InteractionsAPI",
    "MembersAPI",
    "MessagesAPI",
    "RolesAPI",
    "UsersAPI",
    "WebhooksAPI",
]


class DiscordAPI:
    """Fachada das operações REST, agrupadas por recurso.

    Um `Client` tem uma. Também dá para construir sozinha sobre um
    `RESTClient` — é o caminho de teste, e de quem só quer REST sem
    Gateway.
    """

    __slots__ = (
        "_rest",
        "applications",
        "channels",
        "guilds",
        "interactions",
        "members",
        "messages",
        "roles",
        "users",
        "webhooks",
    )

    def __init__(self, rest: RESTClient) -> None:
        self._rest = rest
        self.messages = MessagesAPI(rest)
        self.channels = ChannelsAPI(rest)
        self.users = UsersAPI(rest)
        self.guilds = GuildsAPI(rest)
        self.members = MembersAPI(rest)
        self.roles = RolesAPI(rest)
        self.webhooks = WebhooksAPI(rest)
        self.applications = ApplicationsAPI(rest)
        self.interactions = InteractionsAPI(rest)

    @property
    def rest(self) -> RESTClient:
        """A mecânica por baixo, para o caso raro de precisar da rota crua."""
        return self._rest

    async def aclose(self) -> None:
        """Fecha o pool de conexões HTTP. Idempotente."""
        await self._rest.aclose()

    async def __aenter__(self) -> DiscordAPI:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
