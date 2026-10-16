# KrynCord

Biblioteca assíncrona para criar bots Discord em Python, com implementação
própria das camadas REST e Gateway.

## Objetivos

- API async-first
- REST e Gateway independentes
- Roteamento de comandos e interações
- Cache opcional
- Tipagem e validação
- Testes e benchmarks
- Sem dependência de discord.py ou forks

## Instalação

```bash
pip install kryncord
```

Requer Python 3.11+.

## Uso

```python
import asyncio
import os

from kryncord import Client, Config, Intents, Message


async def main() -> None:
    config = Config(token=os.environ["DISCORD_TOKEN"], intents=Intents.default())

    async with Client(config) as client:

        @client.on("message_create")
        async def responde(message: Message) -> None:
            if message.content == "!ping":
                # `reply` aceita a própria mensagem — o canal sai de lá,
                # e o `message_reference` é montado sozinho.
                await client.api.messages.reply(message, "pong")

        await client.start()
        await asyncio.Event().wait()  # fica no ar


asyncio.run(main())
```

O handler recebe o payload **já interpretado** — um `Message`, não um
`dict`. `message.content` é `None` quando o Discord não mandou texto, e
não `""`; `message.author` é `None` quando não veio autor. Campo ausente
nunca é preenchido com default, porque ausente e default são coisas
diferentes.

O nome do evento aceita as duas formas — `"message_create"` e
`"MESSAGE_CREATE"` chegam ao mesmo handler. E os métodos da API aceitam
ID ou objeto: `send(123, ...)`, `send("123", ...)`,
`send(channel, ...)` e `send(message, ...)` são o mesmo destino.

O `api/` é alcançado por `client.api`, e não por `message.reply()` — os
modelos são dados puros, sem referência a runtime. Ver
[0007](docs/decisions/0007-api-layer.md) para o porquê.

## Desenvolvimento

```bash
python -m pip install -e ".[dev]"
pytest
ruff check src tests
ruff format --check src tests
mypy src/kryncord
```

## Status

**Fase 3 — Core.** O bot recebe payload tipado e consegue responder.
`models/` traz `User`, `Message`, `Channel`, `Guild`, `Member`,
`Attachment`, `Role`, `Ban`, `Webhook`, `ApplicationCommand`,
`Interaction`, `Ready` e os `Partial*` para o que o Discord entrega
incompletos de propósito. `events/` converte o payload e decide a
política de execução — sequencial, exceção isolada, cancelamento
propaga.

`api/` é o vocabulário por recurso sobre a mecânica REST da Fase 1 —
**70 métodos em 9 módulos** (`messages`, `channels`, `members`,
`roles`, `webhooks`, `applications`, `interactions`, `guilds`,
`users`) — e o `Client` liga as duas.

`cache/` + `state/` dão ao bot memória local: `client.cache`, **ligada
por padrão**, guarda guilds, channels, roles e users — `members` e
`messages` são opt-in por serem os que crescem com o servidor. Remoção
híbrida (eventos invalidam o que o gateway anuncia; LRU com teto guarda
o que não tem evento de remoção) e o evento é aplicado **antes** dos
handlers rodarem, senão todo handler leria o estado do evento
anterior.

1516 testes passando. `ruff check`, `ruff format --check` e `mypy` limpos.

Fase 4 entrou em andamento pela metade dos registros de decisão —
`0010`–`0024` fecham a superfície inteira (construtor, registry,
contextos, rota, conversores, componentes, máquina de estados,
middleware, sync, bootstrap, eventos, autocomplete, context menus,
paridade com o discord.js e o bloco de componentes), e cada escolha
passou por um conselho de 22 perfis com veredito e divergência
registrados em `docs/decisions/`. Já em código: o `permissions.py` +
as três `Options` no `Config`, o `commands/` inteiro (option,
definition, validation, instance, registry, context, sync,
autocomplete), a máquina de estados de interação com a superfície do
discord.js (`update`, `defer_update`, `fetch_reply`, `launch_activity`,
`await_responder`), os 17 predicados `is_*()` no modelo, o `responders/`
inteiro (ids, patterns, router, converters, params, context, registry,
decorators, dispatch) e o `components/` inteiro (buttons, selects,
inputs, uploads, choices, rows, displays, modals, colors, validation)
com os embeds e a normalização que serializa no `api/`. Falta
`events/`, middleware como bloco próprio e o `bootstrap`.

| Fase | Conteúdo | Status |
|---|---|---|
| 0 | Pacote, erros, fundação, toolchain, CI | ✅ |
| 1 | REST: rotas, rate limits, buckets | ✅ |
| 2 | Gateway: connect, identify, heartbeat, resume | ✅ |
| 3 | Core: `Client`, `api/`, `models/`, dispatcher, `cache/`, `state/` | ✅ |
| 4 | Interações: commands, responders, components | 🔶 api/ |
| 5 | Benchmarks do cache | ⬜ |

## Estrutura

```text
src/kryncord/       pacote público
  client.py         fachada e ciclo de vida
  config.py         Config, HTTPConfig, GatewayConfig (frozen)
  intents.py        bits de intent + validação privileged
  enums.py          opcodes, close codes, permissões
  errors.py         hierarquia de exceções
  logging.py        namespace kryncord + redact()
  lifecycle.py      tasks supervisionadas, encerramento limpo
  <pacote>/         api, gateway, http, rest, interactions,
                    responders, commands, components, events,
                    models, builders, cache, state, discovery,
                    voice, internal
tests/unit/         testes sem rede
tests/integration/  testes com transportes simulados
docs/decisions/     registros de decisão de arquitetura
ideias/             design da API de alto nível (referência)
base/discord.js/    referência do discord.js (não é código do projeto)
```

Os pacotes de cada fase existem já com `__init__.py` documentando a
responsabilidade. Os arquivos de módulo entram quando tiverem testes e
uso claro — conforme o fim do `docs/internals/architecture.md`.

## Verificação

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy
```

## Decisões

- [0001 — Transporte HTTP: httpx](docs/decisions/0001-http-transport.md)
- [0002 — Transporte WebSocket: websockets](docs/decisions/0002-websocket-transport.md)
- [0003 — Modelos de dados: dataclasses](docs/decisions/0003-data-models.md)
- [0004 — Ordem de construção: REST → Gateway](docs/decisions/0004-build-order.md)
- [0005 — Reconexão do Gateway: classificação de close code](docs/decisions/0005-gateway-reconnect.md)
- [0006 — Eventos: payload tipado e política de dispatch](docs/decisions/0006-event-dispatch.md)
- [0007 — Camada `api/`: vocabulário sobre a mecânica REST](docs/decisions/0007-api-layer.md)

## Licença

MIT
