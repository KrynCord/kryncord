"""O menor bot possível com KrynCord.

Rodar::

    export DISCORD_TOKEN=...   # ou DISCORD_TOKEN no Windows
    python examples/minimal_bot.py

Manda `!ping` num servidor onde o bot está e ele responde `pong`.

Dois pontos que a API decide por você:

* O handler recebe um `Message` interpretado, não um `dict`. Sem o
  intent `MESSAGE_CONTENT`, `message.content` vem `None` — não `""`.
* `client.api` é independente do Gateway: dá para chamar REST antes,
  durante ou depois de `start()`.
"""

from __future__ import annotations

import asyncio
import os

from kryncord import Client, Config, Intents, Message


async def main() -> None:
    config = Config(token=os.environ["DISCORD_TOKEN"], intents=Intents.default())

    async with Client(config) as client:

        @client.on("message_create")
        async def responde(message: Message) -> None:
            if message.content == "!ping":
                # `reply` aceita a própria mensagem: o canal sai de lá e o
                # `message_reference` é montado sozinho.
                await client.api.messages.reply(message, "pong")

        await client.start()
        await asyncio.Event().wait()  # fica no ar até Ctrl+C


if __name__ == "__main__":
    asyncio.run(main())
