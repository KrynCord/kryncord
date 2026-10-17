# KrynCord

[![PyPI version](https://img.shields.io/pypi/v/kryncord.svg)](https://pypi.org/project/kryncord/)
[![Python versions](https://img.shields.io/pypi/pyversions/kryncord.svg)](https://pypi.org/project/kryncord/)
[![License: MIT](https://img.shields.io/pypi/l/kryncord.svg)](LICENSE)
[![tests](https://github.com/KrynCord/kryncord/actions/workflows/tests.yml/badge.svg)](https://github.com/KrynCord/kryncord/actions/workflows/tests.yml)
[![lint](https://github.com/KrynCord/kryncord/actions/workflows/lint.yml/badge.svg)](https://github.com/KrynCord/kryncord/actions/workflows/lint.yml)

An async-first Discord API library for Python, with REST and Gateway
implemented from scratch — no `discord.py` underneath, no fork of one.

**Current release: [`0.1.0b1`](https://pypi.org/project/kryncord/) (beta).**
Requires Python 3.11+.

[Documentation](docs/README.md) · [Changelog](CHANGELOG.md) ·
[PyPI](https://pypi.org/project/kryncord/) ·
[Issues](https://github.com/KrynCord/kryncord/issues)

### Português

Biblioteca assíncrona para bots Discord, com REST e Gateway escritos do
zero. Instalação (é beta, por isso o `--pre`):

```bash
pip install --pre kryncord
```

Depois é `from kryncord import Client, Config, Intents`. O exemplo
completo está logo abaixo em [Quick start](#quick-start), o mapa da
documentação em [`docs/README.md`](docs/README.md) e o passo a passo de
publicação em [`docs/guides/publication.md`](docs/guides/publication.md).
A licença é MIT, o código está em
[github.com/KrynCord/kryncord](https://github.com/KrynCord/kryncord).

## What it is

KrynCord talks to Discord through two layers it owns:

- **REST** — a client with per-bucket rate limiting, retries with
  backoff and multipart upload, wrapped by `client.api`, which turns
  raw JSON into typed models and accepts an object where an ID is
  expected (`send(channel, ...)` and `send(channel.id, ...)` are the
  same destination).
- **Gateway** — Identify, heartbeat with ACK handling, reconnection
  classified by close code, and session resume.

Between them sits the client: it decodes payloads into `Message`,
`Guild`, `Ready` and friends, keeps an optional local cache, and hands
handlers an object rather than a dict.

It is built for people who want the protocol handled correctly and the
API typed, without pulling in a framework on top of it.

## Features

### Implemented

- **Lifecycle** — `async with Client(config)` plus `await client.start()`;
  shutdown closes the socket and the HTTP client in order.
- **REST surface** — 72 methods across 9 modules under `client.api`:
  `messages`, `channels`, `members`, `roles`, `webhooks`,
  `applications`, `interactions`, `guilds`, `users`.
- **Typed payloads** for 15 events: `ready`, `resumed`,
  `message_create`, `message_update`, `message_delete`,
  `message_delete_bulk`, `channel_create`, `channel_update`,
  `channel_delete`, `guild_create`, `guild_update`, `guild_delete`,
  `interaction_create`, `typing_start`, `voice_state_update`.
  Event names accept both spellings — `"message_create"` and
  `"MESSAGE_CREATE"` reach the same handler.
- **Slash commands** — `@command(...)`, options, validation, registry
  and `CommandSync`, which diffs local definitions against what
  Discord has and reports `created` / `updated` / `deleted` /
  `unchanged`.
- **Responders** — `@responder(...)` routes on `custom_id` with
  wildcards, parameter conversion, and `emit_responder` to fire a
  route from anywhere.
- **Components** — buttons, select menus, inputs, labels, modals,
  embeds and the V2 block (`Container`, `Section`, `TextDisplay`,
  `MediaGallery`, `Separator`, `Thumbnail`), with the serialization
  the REST layer expects.
- **Cache** — `client.cache`, on by default, with a `CachePolicy` and
  hit-rate statistics. Guilds, channels, roles and voice states are
  cached out of the box; `members` and `messages` are opt-in because
  they grow with the server (`CachePolicy(members=True, messages=500)`).
- **Errors** — 16 exception classes, all descending from
  `KrynCordError`, so `except KrynCordError` catches the library
  without catching the rest of your program.
- **Typing** — ships `py.typed`; the package passes `mypy --strict`.

### Not implemented yet

- **Voice** — `kryncord.voice` exists only to mark the spot in the
  package map. Voice needs its own gateway, UDP and encryption, and
  there is no functional support.
- **Benchmarks** — the `benchmarks/` directory is empty.
- **Stable releases** — `0.1.0b1` is the only published version, so
  the API may still change before `0.1.0`.

## Installation

KrynCord needs Python 3.11 or newer and has two runtime dependencies
(`httpx`, `websockets`).

```bash
# current state of the project: a beta, so --pre is required
pip install --pre kryncord

# a specific version
pip install --pre kryncord==0.1.0b1

# straight from the repository
pip install git+https://github.com/KrynCord/kryncord.git
```

Without `--pre`, pip ignores `0.1.0b1` because it is a pre-release, and
it looks as if the project does not exist. Once `0.1.0` stable is out,
`pip install kryncord` becomes the normal command.

To work on the library itself:

```bash
git clone https://github.com/KrynCord/kryncord.git
cd kryncord
python -m pip install -e ".[dev]"
```

## Quick start

A bot that answers `!ping` with `pong` — the same code as
[`examples/minimal_bot.py`](examples/minimal_bot.py):

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
                await client.api.messages.reply(message, "pong")

        await client.start()
        await asyncio.Event().wait()  # block until Ctrl+C


asyncio.run(main())
```

Set `DISCORD_TOKEN` and run it. Three details worth knowing:

- `Config` takes `intents` as its first argument; privileged intents
  also have to be listed in `enabled_intents`, or `start()` refuses to
  boot instead of letting Discord reject the Identify later.
- `client.start()` connects and returns — the trailing
  `asyncio.Event().wait()` is what keeps the process alive.
- `async with` closes the connection on the way out, including on an
  exception.

The handler receives a decoded `Message`. `message.content` is `None`
when Discord sent no text (not `""`), and `message.author` is `None`
for a webhook with no author.

## More examples

### Slash command

```python
import asyncio
import os

from kryncord import Client, CommandInteraction, Config, Intents, command
from kryncord.commands import CommandSync


async def main() -> None:
    config = Config(token=os.environ["DISCORD_TOKEN"], intents=Intents.default())

    async with Client(config) as client:

        @command(name="ping", description="Responde pong", registry=client.commands)
        async def ping(interaction: CommandInteraction) -> None:
            await interaction.respond("pong")

        # registers the definition with Discord and reports the diff
        report = await CommandSync(client.commands, client.api.applications).sync()
        print(report.created, report.updated, report.deleted, report.unchanged)

        await client.start()
        await asyncio.Event().wait()


asyncio.run(main())
```

Handlers must be `async` and take exactly one argument — the typed
interaction the decorator delivers (`CommandInteraction` for slash
commands, `ButtonInteraction` for `@button`, …). The annotation is
required and checked at definition time (`HandlerSignatureError`)
rather than failing on every click.

### Reading from the cache

```python
from kryncord import Client, Guild


def ver_guild(client: Client, guild: Guild) -> None:
    # updated before handlers run, so this is already populated
    cached = client.cache.get_guild(guild.id)
    print(cached is not None, client.cache.policy, client.cache.enabled)
    print(client.cache.stats.hit_rate, client.cache.stats.total_evictions)
```

It is local memory, not a mirror of Discord — see the limits below.

### Errors and logging

```python
from kryncord import DiscordAPIError, KrynCordError, RateLimitError
from kryncord.logging import setup_logging

setup_logging("INFO")  # configures the `kryncord.*` loggers

try:
    ...
except RateLimitError:
    ...  # Discord said 429 and the client already waited and retried
except DiscordAPIError:
    ...  # a non-retryable API error
except KrynCordError:
    ...  # anything else from the library
```

Token values are passed through `kryncord.logging.redact()` before
being logged.

## Documentation

Everything lives in the repository — there is no separate docs site
yet.

| Where | What |
|---|---|
| [`docs/README.md`](docs/README.md) | Index and reading order |
| [`docs/internals/architecture.md`](docs/internals/architecture.md) | Full architecture: layers, modules, boundaries |
| [`docs/decisions/`](docs/decisions/) | 31 ADRs — why each decision was made |
| [`docs/api/`](docs/api/) | Surface specs: components (V1, V2, modals) and typed interactions |
| [`docs/guides/publication.md`](docs/guides/publication.md) | Release process: TestPyPI, PyPI, versioning |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed in each release |
| [`examples/`](examples/) | Runnable example |

## Architecture

```text
src/kryncord/
  client.py     facade and lifecycle
  config.py     Config, HTTPConfig, GatewayConfig (frozen)
  intents.py    intent bits + privileged validation
  errors.py     exception hierarchy
  http/         transport, buckets, rate limits, retries
  gateway/      connect, identify, heartbeat, resume
  rest/         routes and raw requests
  api/          typed vocabulary on top of REST (client.api)
  models/       User, Message, Guild, Interaction, ...
  events/       payload decoding and dispatch policy
  commands/     definitions, options, registry, sync
  interactions/ typed interactions and response state machine
  responders/   custom_id routing and converters
  components/   buttons, selects, modals, embeds
  cache/        policy, memory cache, statistics
  state/        connection state fed by the gateway
tests/          unit, integration and contract suites
docs/           architecture, ADRs and guides
```

Two boundaries the code keeps deliberately: `rest/` knows routes and
limits but not models, and `models/` are plain data with no reference
to the runtime — which is why replies go through
`client.api.messages.reply(...)` rather than `message.reply(...)`.
See [ADR 0007](docs/decisions/0007-api-layer.md).

## Compatibility

**Tested:** Python 3.11, 3.12 and 3.13, on both Linux and Windows —
that is the CI matrix in [`.github/workflows/tests.yml`](.github/workflows/tests.yml),
together with `ruff check`, `ruff format --check` and `mypy --strict`.

**Expected to work:** any platform CPython runs on, since the
dependencies (`httpx`, `websockets`) are pure Python.

**Discord side:** KrynCord targets the public Discord API. Payload
shape, rate limits and feature availability are Discord's call, not
the library's.

## Limits worth knowing

- **`MESSAGE_CONTENT` is privileged.** Enable it in the Discord
  Developer Portal before requesting the intent, or the Identify is
  rejected. Without the intent, `message.content` arrives `None` for
  messages from other users — that is Discord's behaviour, not a bug
  in the library.
- **Intents are checked twice.** Whatever `Config(intents=...)` asks
  for must also be covered by `enabled_intents`, or `start()` raises
  before connecting.
- **The cache is not a database.** It holds what the gateway sent, is
  lost on restart, and is capped: `users` and `messages` are LRU with
  a limit, so a long-running bot will evict old entries.
- **Absent is not default.** A field Discord omitted arrives as
  `None` and is never filled in with a conventional value. `None` and
  `0` mean different things.
- **Network failures are not handled for you.** The gateway
  reconnects and resumes on its own; the REST client retries what is
  safe to retry. Beyond that, connection problems surface as
  `GatewayError` / `HTTPError` for your code to decide on.

## Development

```bash
python -m pip install -e ".[dev]"
pytest                            # 1667 tests, no network needed
ruff check src tests
ruff format --check src tests
mypy                              # strict, whole package
```

These are exactly the checks CI runs on every push. Tests use
simulated transports, so no Discord token is required to run them.

Bug reports and proposals go through
[GitHub Issues](https://github.com/KrynCord/kryncord/issues). There is
no `CONTRIBUTING.md` yet — a pull request that keeps those four
commands green is the working rule.

## License

MIT — see [`LICENSE`](LICENSE). Copyright (c) 2026 Gustavo Silva.
