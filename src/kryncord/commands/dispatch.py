"""Despacho de `APPLICATION_COMMAND` — a cadeia por nível (`0022`).

O contrato é o da ideia 04 §4: `run()` **devolve** um valor, e o
dispatcher injeta como segundo parâmetro do nível seguinte. Não há um
segundo mecanismo, e não deveria — uma lista de "também passa isto"
seria um protocolo paralelo que só existe no nosso código.

```
command.run(inter)  ->  grupo.run(inter, valor)  ->  sub.run(inter, valor)
```

O primeiro parâmetro é sempre a **interação tipada** (`0031`):
`CommandInteraction` para CHAT_INPUT, `UserCommandInteraction` para
menu USER, e assim por diante — o dispatcher escolhe a classe pelo tipo
do comando registrado, e o handler escreve a anotação que corresponde.

## O valor pode não existir

A ideia 04 §6 decide que o `run` da raiz é **opcional** — o `command.py`
pode ser só uma âncora. Quando ele não existe, não há valor a injetar, e
o filho recebe `None`.

Isso é proposital: receber `None` e reclamar com `DispatchError
("anotava StoreData, recebeu NoneType")` diz exatamente o que está
errado. Chamar sem o argumento daria `TypeError: missing 1 required
positional argument`, que aponta para a linha do filho e não para a
ausência do pai.

## Filho sem parâmetro descarta

A tabela do `0026` §3 é o contrato, e ela tem um caso que não é erro:
`async def add(inter)` num filho cujo pai devolve alguma coisa. O valor é
descartado, e é correto — é como se declara "eu não uso o que vem de
cima" sem inventar um parâmetro morto só para a assinatura fechar.

A checagem de tipo só existe **quando há anotação**. Sem anotação, sem
contrato (ideia 04 §4: "sem anotação = sem checagem").
"""

from __future__ import annotations

import contextlib
import inspect
from collections.abc import Callable, Iterable, Mapping
from types import UnionType
from typing import Any, Union, cast, get_args, get_origin, get_type_hints

from kryncord.api import interacoes_de
from kryncord.commands.instance import CommandInstance
from kryncord.commands.option import OptionType
from kryncord.enums import ApplicationCommandType
from kryncord.errors import BlockHandlers, DispatchError
from kryncord.interactions.commands import (
    CommandInteraction,
    classe_de_comando,
)
from kryncord.interactions.response import InteractionContext
from kryncord.internal.compose import block
from kryncord.logging import get_logger
from kryncord.models.interaction import Interaction

_log = get_logger("commands")

#: `(nº de posicionais, anotação do 2º parâmetro, aceita *args)`, por
#: handler. `get_type_hints` resolve nomes em escopo de módulo, e a
#: ideia 04 §4 manda isso acontecer no registro — cachear aqui entrega
#: o mesmo efeito sem amarrar o cache à vida do `CommandInstance`.
_ASSINATURAS: dict[Any, tuple[int, Any, bool]] = {}


async def dispatch_application_command(
    interaction: Interaction,
    api: Any,
    *,
    registry: Any,
    client: Any = None,
    state: dict[str, Any] | None = None,
    middleware: Iterable[Callable[..., Any]] = (),
    on_error: Callable[..., Any] | None = None,
    on_not_found: Callable[..., Any] | None = None,
) -> bool:
    """Rodeia um `APPLICATION_COMMAND` e executa a cadeia de níveis.

    `True` se um comando atendeu (middleware incluída); `False` se
    ninguém — e aí o `on_not_found` **de comandos** já rodou, se houver
    (`0026` §4: o `on_not_found` é o do `Options` correspondente, e
    comandos e responders são `Options` diferentes).

    A cadeia inteira é um `try`: exceção de um nível chama o `on_error`
    e devolve `True` — o clique **foi** atendido, mesmo que tenha
    falhado no meio. Devolver `False` faria o chamador tratar como
    "ninguém cuidou" e disparar o `on_not_found` em cima de uma falha,
    que é como se vê "algo deu errado" duas vezes.
    """
    api = interacoes_de(api)
    data = interaction.data or {}
    nome = data.get("name")
    if not isinstance(nome, str):
        return False

    instancia = instancia_de(registry, interaction)
    if instancia is None:
        await _nao_encontrado(on_not_found, interaction, api, client, nome)
        return False

    inter = _interacao(interaction, api, instancia.type, client, state)

    cadeia = (*middleware, *instancia.middleware)
    try:
        for item in cadeia:
            await item(inter, block)
        await _cascata(instancia, inter, data)
    except BlockHandlers:
        #: Quem chamou `block()` respondeu ali — o clique foi atendido,
        #: e `on_error` não roda (`0017`: bloqueio é tratamento).
        return True
    except Exception as exc:
        #: O `on_error` **deste comando** vence o do `Options`, e o do
        #: `Options` completa (`0030` §1) — mesma relação de prioridade
        #: da middleware local sobre a global (`0017`). Inverter faria
        #: um global sobrescrever silenciosamente o que o autor do
        #: comando escreveu.
        alvo = instancia.on_error if instancia.on_error is not None else on_error
        await _erro(exc, inter, alvo)
        return True
    return True


def _interacao(
    interaction: Interaction,
    api: Any,
    tipo_comando: ApplicationCommandType,
    client: Any,
    state: dict[str, Any] | None,
) -> CommandInteraction:
    """A interação tipada deste dispatch — a classe vem do tipo do comando.

    `CommandInteraction` para CHAT_INPUT, `UserCommandInteraction` para
    menu USER, e assim por diante (`0031`). A escolha vem do **registro**
    (`instancia.type`), que é o que foi publicado no Discord — nunca da
    anotação, que seria só uma promessa do autor.
    """
    classe = classe_de_comando(tipo_comando)
    return classe(
        InteractionContext(interaction, api),
        client=client,
        state=state if state is not None else {},
    )


async def _cascata(
    instancia: CommandInstance, inter: CommandInteraction, data: Mapping[str, Any]
) -> None:
    """Roda os níveis da esquerda para a direita, injetando o valor.

    `None` no meio é o valor de quem não tinha handler — ele simplesmente
    não participa, e o que vem de cima continua andando. O `run` da raiz
    é opcional (ideia 04 §6) e este é o lugar onde isso vira código.
    """
    valor = await instancia.run(inter)

    grupo, sub = _caminho(data)
    if grupo is not None:
        handler_grupo = instancia.grupo_handler(grupo)
        if handler_grupo is not None:
            valor = await _injeta(
                handler_grupo, inter, valor, f"grupo {grupo!r} de {instancia.name!r}"
            )
        handler_sub = instancia.groups.get(grupo, {}).get(sub or "")
    elif sub is not None:
        handler_sub = instancia.subcommands.get(sub)
    else:
        handler_sub = None

    if sub is None:
        return
    if handler_sub is None:
        raise DispatchError(
            f"comando {instancia.name!r}: o Discord entregou o subcomando "
            f"{sub!r} que não está registrado — registro e payload "
            "divergiram; rode `sync` de novo"
        )
    await _injeta(handler_sub, inter, valor, f"subcomando {sub!r} de {instancia.name!r}")


# -----------------------------------------------------------------------
# Injeção de valor
# -----------------------------------------------------------------------


async def _injeta(
    handler: Callable[..., Any], inter: CommandInteraction, valor: Any, onde: str
) -> Any:
    """Chama o filho com o valor, se ele aceita, e com o tipo que prometeu.

    Três saídas, e as três estão na tabela do `0026` §3:

    * sem parâmetro declarado e sem `*args` → o valor é descartado;
    * anotação que não bate → `DispatchError`, citando o quê e o quê;
    * sem anotação → passa como está (ideia 04 §4).
    """
    n_posicionais, anotacao, varargs = _parametros(handler)
    if n_posicionais < 2 and not varargs:
        return await _chama(handler, inter)

    if not _confere(anotacao, valor):
        raise DispatchError(
            f"{onde}: anotava `{_nome(anotacao)}`, recebeu `{type(valor).__name__}` ({valor!r})"
        )
    return await _chama(handler, inter, valor)


async def _chama(handler: Callable[..., Any], inter: CommandInteraction, *args: Any) -> Any:
    """Chama e espera, sem virar coroutine pendurada."""
    return await handler(inter, *args)


def _parametros(handler: Callable[..., Any]) -> tuple[int, Any, bool]:
    """`(nº de posicionais, anotação do 2º, aceita *args)`.

    `None` como anotação significa "não declarou" — e é diferente de
    `Any`, que é "declarou que aceita tudo". Os dois passam, mas a
    mensagem do `DispatchError` diz qual dos dois o usuário escreveu.
    """
    try:
        cacheado = _ASSINATURAS.get(handler)
    except TypeError:
        # Objeto não hashável — callable custom sem `__hash__`. Não dá
        # para memoizar, e calcular a cada dispatch é só mais lento.
        return _calcula(handler)
    if cacheado is not None:
        return cacheado

    resultado = _calcula(handler)
    _ASSINATURAS[handler] = resultado
    return resultado


def _calcula(handler: Callable[..., Any]) -> tuple[int, Any, bool]:
    """A checagem de verdade, sem cache — `get_type_hints` incluído.

    Falha de resolução (forward ref solta, import faltando) vira
    "sem anotação" em vez de explodir: quem escreveu a anotação ruim
    já tem o `mypy`, e o runtime não pode ser mais rígido que o
    verificador estático sem também ser mais errado.
    """
    try:
        assinatura = inspect.signature(handler)
        hints = get_type_hints(handler)
    except (TypeError, ValueError):
        return (2, None, True)

    posicionais = [
        p
        for p in assinatura.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    varargs = any(p.kind is p.VAR_POSITIONAL for p in assinatura.parameters.values())

    if len(posicionais) < 2:
        return (len(posicionais), None, varargs)

    try:
        return (len(posicionais), hints.get(posicionais[1].name), varargs)
    except Exception:
        return (len(posicionais), None, varargs)


def _confere(anotacao: Any, valor: Any) -> bool:
    """Se o valor satisfaz a anotação — união desmontada, `Any` passa."""
    if anotacao is None or anotacao is Any or anotacao is object:
        return True

    origem = get_origin(anotacao)
    if origem is UnionType or origem is Union:
        return any(_confere(membro, valor) for membro in get_args(anotacao))
    if not isinstance(anotacao, type):
        # Protocolo, `Callable`, forward ref não resolvida — não dá
        # para `issubclass`, e inventar regra seria mais errado.
        return True
    return isinstance(valor, anotacao)


def _nome(tipo: Any) -> str:
    """Nome legível de uma anotação, para a mensagem do `DispatchError`."""
    if tipo is None:
        return "sem anotação"
    return getattr(tipo, "__name__", str(tipo))


# -----------------------------------------------------------------------
# Localização
# -----------------------------------------------------------------------


def _tipo_de(data: Mapping[str, Any]) -> ApplicationCommandType:
    """O tipo da interação, com o default do Discord (CHAT_INPUT)."""
    bruto = data.get("type")
    if isinstance(bruto, int) and not isinstance(bruto, bool):
        try:
            return ApplicationCommandType(bruto)
        except ValueError:
            return ApplicationCommandType.CHAT_INPUT
    return ApplicationCommandType.CHAT_INPUT


def instancia_de(registry: Any, interaction: Interaction) -> CommandInstance | None:
    """O comando que esta interação invocou, ou `None`.

    A mesma busca do despacho de comando, exportada porque o de
    autocomplete precisa dela: ele quer saber **quem** invocou antes de
    responder, e reimplementar a procura faria os dois lugares
    divergirem — um achando comando que o outro não acha.

    Duas tentativas, e a segunda não é conveniência: um comando
    **global** invocado numa guild entrega `guild_id` no payload, e a
    chave dele é `(tipo, nome, None)`. Sem o fallback, todo comando
    global deixaria de funcionar assim que entrasse em um servidor — que
    é o único lugar onde alguém consegue clicar nele.
    """
    data = interaction.data or {}
    nome = data.get("name")
    if not isinstance(nome, str):
        return None

    achado = registry.get(_tipo_de(data), nome, interaction.guild_id)
    if achado is not None:
        return cast("CommandInstance | None", achado)
    if interaction.guild_id is None:
        return None
    return cast("CommandInstance | None", registry.get(_tipo_de(data), nome, None))


def _caminho(data: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """`(grupo, subcomando)` a partir dos `options` aninhados.

    Um comando simples devolve `(None, None)`; um sub de primeiro nível,
    `(None, sub)`; um dentro de grupo, `(grupo, sub)`. Os dois `None`
    são o caso comum, e é por isso que a tupla é o retorno — um `dict`
    seria mais lido e não diria nada a mais.
    """
    bruto = data.get("options")
    if not isinstance(bruto, list) or not bruto:
        return (None, None)

    primeiro = bruto[0]
    if not isinstance(primeiro, Mapping):
        return (None, None)

    nome_primeiro = primeiro.get("name")
    if primeiro.get("type") == OptionType.SUB_COMMAND_GROUP:
        subs = primeiro.get("options")
        sub = None
        if isinstance(subs, list) and subs and isinstance(subs[0], Mapping):
            sub = subs[0].get("name")
        return (nome_primeiro if isinstance(nome_primeiro, str) else None, sub)

    return (None, nome_primeiro if isinstance(nome_primeiro, str) else None)


# -----------------------------------------------------------------------
# Interação
# -----------------------------------------------------------------------


async def _nao_encontrado(
    on_not_found: Callable[..., Any] | None,
    interaction: Interaction,
    api: Any,
    client: Any,
    nome: str,
) -> None:
    """Sem comando registrado — é o `on_not_found` de comandos que decide.

    Não existe resposta automática aqui, pelo mesmo motivo do `0026` §4:
    um "isso não foi configurado" na cara do usuário piora o bot que
    está no meio de um deploy. Quem quer avisar, avisa.
    """
    if on_not_found is None:
        _log.warning(
            "comando %r sem handler registrado — nenhum on_not_found em `Config(commands=...)`",
            nome,
        )
        return
    inter = CommandInteraction(InteractionContext(interaction, api), client=client)
    try:
        await on_not_found(inter)
    except Exception:
        _log.exception("on_not_found do comando %r falhou", nome)


async def _erro(
    exc: Exception, inter: CommandInteraction, on_error: Callable[..., Any] | None
) -> None:
    """O `on_error` de comando, ou o default do `0026` §11.

    O default não é só logar: ele tenta **uma** efêmera se ninguém
    respondeu, e engole o erro dessa tentativa. Sem isto, um handler que
    falha antes do `defer` deixa o usuário vendo "falha no interagir com
    esta aplicação" — que é a mensagem mais ruim que o Discord tem.
    """
    if on_error is None:
        _log.error("Erro no comando %s", inter.interaction.data, exc_info=exc)
        await _tenta_efemera(inter)
        return
    try:
        await on_error(inter, exc)
    except Exception:
        _log.exception("on_error do comando também falhou")


async def _tenta_efemera(inter: CommandInteraction) -> None:
    """Uma efêmera de desculpa, se ainda dá tempo — e só uma.

    Engolida de propósito: se a efêmera também falhar (token expirado,
    permissão, rede), o erro verdadeiro é o que já está no log. Duas
    pilhas para o mesmo problema não ajudam ninguém.
    """
    if inter.is_responded():
        return
    with contextlib.suppress(Exception):
        await inter.respond(
            "Algo deu errado ao executar este comando. O erro já foi registrado.",
            ephemeral=True,
        )
