"""`@command` e `create_command` — o registro de alto nível (`0026` §1).

Dois níveis, como a ideia 02 §2 pede:

```python
# o decorator direto — o caso de 90% dos comandos
@command(name="ping", description="Responde com pong")
async def ping(interaction: CommandInteraction) -> None: ...

# a âncora + handler — o caso da ideia 04 §2, com filhos em outros módulos
command = create_command(name="store")


@command()
async def run(interaction: CommandInteraction) -> StoreData | None: ...

command.sub("close", close_handler)
```

`create_command` devolve a `CommandInstance` (`0011` fechou que é isso
que ele devolve) e `command` devolve a **função original**. Trocar o
objeto da função por uma instância quebraria `@command` acima de
`@staticmethod`, `functools.wraps` e qualquer teste que inspeciona a
função — e não ganharia nada, porque a `CommandInstance` é o que o
registry guarda, e é onde ela é usada.

## O escopo é declarado aqui, e só aqui

`is_global=` e `guild=` são o `0009` K1. Nem um dos dois significa o
default de `Config(commands=CommandOptions(...))`, e a instância fica
**adiada** até o `Client.start()` re-chaveá-la (`0028`). O `deferido` é
a única diferença entre os dois caminhos: a chave é a mesma, e o
`reescopiar` é no-op quando `guilds=()`.

## Validação é na importação

`name` vazio, tipo sem `description`, opção duplicada, handler
síncrono, `is_global` junto com `guild` — tudo `TypeError` ou
`CommandDefinitionError` na linha do decorator. Descobrir no clique
seria descobrir depois do bot publicado, e a mensagem do Discord
("algo deu errado") não aponta para arquivo nenhum.

A anotação do primeiro parâmetro entra na mesma conta (`0031`): a
classe entregue vem do `type=` do comando, e o decorator confere se a
anotação diz a mesma coisa — `HandlerSignatureError` na importação,
não um `AttributeError` no clique.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from typing import Any

from kryncord.commands.definition import CommandDefinition
from kryncord.commands.instance import CommandInstance, Handler, _exige_assincrono
from kryncord.commands.option import Option
from kryncord.commands.validation import validate_definition
from kryncord.enums import ApplicationCommandType
from kryncord.errors import CommandDefinitionError
from kryncord.interactions.commands import classe_de_comando
from kryncord.internal.signatures import valida_interacao
from kryncord.permissions import parse_permissions_list

#: O registry para onde registrar quando não apontam outro. O import é
#: **adiado** pelo mesmo motivo do `@event` (`events/decorators.py`):
#: `kryncord.registry` importa `commands/registry.py`, e este módulo
#: importa `kryncord.registry` também — o ciclo quebraria com
#: "partially initialized module" dependendo de qual dos dois o usuário
#: importar primeiro.


def create_command(
    *,
    name: str,
    description: str = "",
    type: ApplicationCommandType = ApplicationCommandType.CHAT_INPUT,
    is_global: bool | None = None,
    guild: int | Sequence[int] | None = None,
    options: tuple[Option, ...] = (),
    default_member_permissions: Any = None,
    dm_permission: bool | None = None,
    nsfw: bool = False,
    name_localizations: Any = None,
    description_localizations: Any = None,
    middleware: Any = None,
    on_error: Handler | None = None,
    registry: Any = None,
) -> CommandInstance:
    """Cria o comando e o registra, devolvendo a `CommandInstance`.

    É a forma da ideia 04 §2: um objeto ao qual `.sub()`, `.group()` e
    `.autocomplete()` se penduram — e que também funciona como decorator
    (`@command_instance()` ou `@command_instance`).
    """
    destino = registry if registry is not None else _global()
    escopos, deferido = _escopos_de(name, is_global, guild)

    definition = CommandDefinition(
        name=name,
        description=description,
        type=type,
        scope=escopos[0],
        options=tuple(options),
        default_member_permissions=parse_permissions_list(
            default_member_permissions,
            where=f"command({name!r}).default_member_permissions",
        ),
        dm_permission=dm_permission,
        nsfw=nsfw,
        name_localizations=name_localizations,
        description_localizations=description_localizations,
    )
    validate_definition(definition)

    instancia = CommandInstance(definition)
    instancia._middleware = _cadeia(middleware)
    instancia._on_error = on_error
    instancia._deferido = deferido
    destino.register(instancia, escopos)
    return instancia


def command(
    *,
    name: str,
    description: str = "",
    type: ApplicationCommandType = ApplicationCommandType.CHAT_INPUT,
    is_global: bool | None = None,
    guild: int | Sequence[int] | None = None,
    options: tuple[Option, ...] = (),
    default_member_permissions: Any = None,
    dm_permission: bool | None = None,
    nsfw: bool = False,
    name_localizations: Any = None,
    description_localizations: Any = None,
    middleware: Any = None,
    on_error: Handler | None = None,
    registry: Any = None,
) -> Callable[[Handler], Handler]:
    """Decorator de comando. Devolve a **função original**.

    O handler tem que ser `async def` (`0010`), aceitar pelo menos um
    parâmetro e anotá-lo com a interação certa para o `type=` — os três
    checados aqui, na importação (`0031`). Um `async def ping()` sem
    parâmetros registraria um comando que falharia com `TypeError` em
    cada clique; um anotado com a classe errada leria `interaction.options`
    inexistente — e a mensagem do Discord não diria nada sobre
    `inspect.signature`.

    **`on_not_found` não existe aqui** (`0030`): ele é uma pergunta do
    `Options` — "eu não conheço este nome" — e uma `CommandInstance`
    só existe se o nome for conhecido. A pergunta não se aplica a ela.
    """

    def decorador(fn: Handler) -> Handler:
        _exige_assincrono(fn, f"handler do comando {name!r}")
        valida_interacao(
            fn,
            classe_de_comando(type),
            f"handler do comando {name!r}",
        )
        instancia = create_command(
            name=name,
            description=description,
            type=type,
            is_global=is_global,
            guild=guild,
            options=options,
            default_member_permissions=default_member_permissions,
            dm_permission=dm_permission,
            nsfw=nsfw,
            name_localizations=name_localizations,
            description_localizations=description_localizations,
            middleware=middleware,
            on_error=on_error,
            registry=registry,
        )
        instancia._handler = fn
        return fn

    return decorador


# -----------------------------------------------------------------------
# Escopo
# -----------------------------------------------------------------------


def _escopos_de(
    nome: str,
    is_global: bool | None,
    guild: int | Sequence[int] | None,
) -> tuple[tuple[int | None, ...], bool]:
    """`(escopos, deferido)` — a tabela do `0028` §1.

    `deferido` é `True` só quando o decorator não declarou nada: aí o
    escopo vem do `Config`, e o `Client.start()` re-chaveia.
    """
    if guild is not None and is_global is not None:
        raise CommandDefinitionError(
            f"comando {nome!r}: `is_global` e `guild` juntos — são dois "
            "sinais contradizendo sobre o mesmo comando (0009 K1). Escolha "
            "um: `is_global=True` para o global, `guild=...` para guilds."
        )

    if guild is not None:
        return _guilds(guild, nome), False

    if is_global is False:
        raise CommandDefinitionError(
            f"comando {nome!r}: `is_global=False` sem `guild` — o comando "
            "não iria a lugar nenhum, e o sync o mandaria para a rota "
            "global em silêncio. Passe `guild=`."
        )

    if is_global is True:
        return (None,), False

    # Nenhum declarado: default de `Config(commands=...)`, e o default é
    # global — `CommandOptions.guilds=()` significa "padrão é global"
    # (`0010`). O `reescopiar` no `start()` faz nada se ninguém mudou.
    return (None,), True


def _guilds(guild: int | Sequence[int], nome: str) -> tuple[int | None, ...]:
    """Normaliza `guild=` em tupla de escopos, rejeitando o que não é id.

    `bool` antes de `int`, como já faz o resto da biblioteca: um JSON
    com `"guild": true` é JSON quebrado, não a guild 1 — e a coerção
    silenciosa faria o comando ir para o servidor errado.
    """
    candidatos: Sequence[Any]
    if isinstance(guild, bool):
        raise CommandDefinitionError(
            f"comando {nome!r}: guild={guild!r} — `bool` é rejeitado antes "
            "de `int`; um JSON com `true` é JSON quebrado, não a guild 1"
        )
    if isinstance(guild, int):
        candidatos = (guild,)
    elif isinstance(guild, Sequence) and not isinstance(guild, (str, bytes)):
        candidatos = guild
    else:
        raise CommandDefinitionError(
            f"comando {nome!r}: guild={guild!r} — esperado `int` ou sequência de `int`"
        )

    saida = tuple(int(g) for g in candidatos)
    if not saida:
        raise CommandDefinitionError(f"comando {nome!r}: `guild=` vazio")
    return saida


def _cadeia(middleware: Any) -> tuple[Any, ...]:
    """Uma middleware vira tupla de um; `None` vira cadeia vazia.

    O `Options` aceita **uma** função por tipo (`0017`); para várias, o
    usuário usa `compose` — é para isso que ele existe.
    """
    if middleware is None:
        return ()
    if inspect.iscoroutinefunction(middleware):
        return (middleware,)
    if callable(middleware):
        return (middleware,)
    raise TypeError(
        f"middleware tem que ser uma função assíncrona, recebi {middleware!r}. "
        "Para várias, use `compose(m1, m2)`."
    )


def _global() -> Any:
    """O `CommandRegistry` do registry global — default de todo `@command`.

    Adiado de propósito: `kryncord.registry` importa `commands/registry`,
    e este módulo importaria `kryncord.registry` — o ciclo quebraria com
    "cannot import name ... from partially initialized module" em vez
    de funcionar, dependendo da ordem de import do usuário.
    """
    from kryncord.registry import registry as _global_registry

    return _global_registry.commands


__all__ = ["command", "create_command"]
