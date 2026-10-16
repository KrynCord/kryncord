"""`@event` — o registro de alto nível, com validação na importação.

A diferença para `client.on` é o `EventContext` na frente dos
argumentos, e é a única (`0020`): uma tabela (`EVENT_PAYLOADS`), dois
caminhos, e a diferença é o contexto.

Tudo que este módulo faz existe para que o erro apareça **na
importação**. Aridade errada, evento que não existe, `ready` declarado
duas vezes — são coisas que sem validação viram "handler que nunca roda,
sem erro visível", que é o pior sintoma de diagnosticar. Com validação,
viram um traceback apontando a linha do decorator.

## A função original volta

`@event` devolve a função, não a `EventEntry`. Trocar o objeto da
função por um registro quebraria `functools.wraps`, `@staticmethod` acima
do decorator, e qualquer teste que inspeciona a função — e não ganharia
nada: a `EventEntry` vive no dispatcher, que é onde ela é usada.

## Anotação é conferida com folga

A ideia 10 §2 pedia "anotação errada → erro". O conselho (`0025` §3)
reduziu a regra ao que é honesto: a anotação é conferida quando
`get_type_hints` resolve **e** o tipo declarado é incompatível com o da
tabela. `Any`, `object`, ausência e erro de resolução passam — a
anotação é ganho de editor, não contrato de runtime, e falhar num alias
que o `mypy` aceita seria pior que o alias.
"""

from __future__ import annotations

import difflib
import inspect
import types
from collections.abc import Callable, Iterable
from typing import Any, Union, get_args, get_origin, get_type_hints

from kryncord.errors import EventDefinitionError
from kryncord.events.dispatcher import EventDispatcher
from kryncord.events.names import normalize_event_name
from kryncord.events.payloads import EVENT_PAYLOADS

#: O handler que o decorator aceita. `*args` é permitido (`K9`), e a
#: sincronidade é validada pelo `EventDispatcher.add`.
Handler = Callable[..., Any]


def event(
    nome: str,
    *,
    name: str | None = None,
    tags: Iterable[str] = (),
    once: bool | None = None,
    middleware: Iterable[Callable[..., Any]] = (),
    registry: EventDispatcher | None = None,
) -> Callable[[Handler], Handler]:
    """Registra um handler para o evento, validando tudo que dá para
    saber antes do primeiro dispatch.

    `nome` é o evento em ``snake_case`` (a forma ``SCREAMING`` também
    é aceita, como em `client.on`). `name` é o identificador humano que
    aparece nos logs — default: o nome da função.

    `ready` é forçado a `once=True` (`ideia 10` §3): o anúncio de
    sessão acontece uma vez, e um `ready` disparando duas vezes é um
    bot que "conecta" duas vezes. Declarar `once=False` explicitamente é
    `EventDefinitionError`, não um silêncio.
    """
    destino = registry if registry is not None else _dispatcher_global()
    chave = normalize_event_name(nome)
    _valida_nome(chave, destino)

    # `once=None` é "não declarou". O default do parâmetro é `None` e
    # não `False` porque os dois significados são diferentes: não
    # declarar `once` é deixar o padrão do dispatcher, e declarar
    # `once=False` para `ready` é contradizer o contrato na cara. Um
    # `False` como default tornaria os dois indistinguíveis — e
    # `@event("ready")`, o uso de 90% dos bots, cairia no erro.
    if chave == "ready" and once is False:
        raise EventDefinitionError(
            "`ready` é once=True por contrato (ideia 10 §3): o anúncio de "
            "sessão acontece uma vez. Não declare `once=False` — registre "
            "outro handler se quiser rodar de novo, ou use `client.on`."
        )

    def decorador(fn: Handler) -> Handler:
        _valida_aridade(chave, fn)
        _valida_anotacoes(chave, fn)
        destino.add(
            chave,
            fn,
            label=name if name is not None else str(getattr(fn, "__qualname__", repr(fn))),
            tags=tags,
            once=True if chave == "ready" else bool(once),
            with_context=True,
        )
        return fn

    return decorador


def _dispatcher_global() -> EventDispatcher:
    """O `EventDispatcher` do registry global — o default de todo `@event`.

    O import é **adiado de propósito**: `kryncord.registry` importa
    `events/dispatcher.py`, e este módulo importa `events/dispatcher.py`
    também — mas se importasse `kryncord.registry` no topo, o ciclo
    `registry → events.dispatcher → decorators → registry` quebraria com
    "cannot import name 'registry' from partially initialized module",
    dependendo de qual dos dois o usuário importar primeiro.

    Adiado, o lookup acontece depois de os dois estarem carregados, e a
    ordem de import deixa de importar.
    """
    from kryncord.registry import registry as _global

    return _global.events


def _valida_nome(chave: str, destino: EventDispatcher) -> None:
    """Rejeita evento que a biblioteca não entrega — com sugestão.

    A tabela do `0020` é o contrato: só os quinze têm assinatura
    definida. Aceitar qualquer nome faria o handler nunca rodar em
    silêncio — o pior resultado possível, porque parece funcionar até o
    dia em que alguém procura o log.
    """
    if chave in EVENT_PAYLOADS:
        return
    # A sugestão compara em minúsculas: `MESSAGE_CREATES` é um typo do
    # formato SCREAMING, que a biblioteca aceita como forma de escrever
    # o nome (`0025`). Comparar o SCREAMING com as chaves em
    # snake_case não achava sugestão nenhuma — e é justamente o typo
    # mais comum de se escrever.
    candidato = chave.lower()
    sugestoes = difflib.get_close_matches(candidato, sorted(EVENT_PAYLOADS), n=3, cutoff=0.5)
    dica = f" Quer dizer: {', '.join(sugestoes)}?" if sugestoes else ""
    raise EventDefinitionError(
        f"Evento {chave!r} não existe — a biblioteca entrega só os "
        f"{len(EVENT_PAYLOADS)} de `EVENT_PAYLOADS` (docs/decisions/0025).{dica}"
    )


def _valida_aridade(chave: str, fn: Handler) -> None:
    """Confere quantos argumentos o handler recebe, na importação.

    Esperado é `1 + len(args)` — o `EventContext` na frente, que é o que
    `@event` promete. Handler com `*args` pula a checagem (`K9`): quem
    escreveu `*args` disse que não quer número nenhum.
    """
    esperado = 1 + len(EVENT_PAYLOADS[chave])
    if _tem_variadic(fn):
        return
    recebidos = len(
        [
            p
            for p in inspect.signature(fn).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
    )
    if recebidos != esperado:
        raise EventDefinitionError(
            f"Handler de {chave!r} recebe {recebidos} argumento(s), e o "
            f"evento entrega {esperado} (EventContext + "
            f"{len(EVENT_PAYLOADS[chave])}): "
            f"async def {getattr(fn, '__qualname__', 'handler')}("
            f"ctx, {', '.join(f'a{i}' for i in range(len(EVENT_PAYLOADS[chave])))})"
        )


def _valida_anotacoes(chave: str, fn: Handler) -> None:
    """Confere a anotação de cada argumento, quando dá para conferir.

    Só reclama de **incompatibilidade**. Uma anotação que `get_type_hints`
    não resolve (forward ref solta, import faltando) passa — o `mypy` já
    reclama dela, e o runtime não pode ser mais rígido que o verificador
    estático sem também ser mais errado.
    """
    if _tem_variadic(fn):
        return
    try:
        hints = get_type_hints(fn)
    except Exception:
        # Nome não resolvido no escopo do módulo. Quem escreveu a
        # anotação ruim já tem o `mypy`; aqui não é o lugar de cobrar.
        return

    esperados = EVENT_PAYLOADS[chave]
    parametros = [
        p
        for p in inspect.signature(fn).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    # O primeiro é o `ctx`, que não está na tabela — ele é o contexto,
    # não um argumento do evento.
    for indice, parametro in enumerate(parametros[1:]):
        if indice >= len(esperados):
            break
        declarado = hints.get(parametro.name)
        if declarado is None or not _compativel(declarado, esperados[indice]):
            raise EventDefinitionError(
                f"Handler de {chave!r}: `{parametro.name}: "
                f"{_nome(declarado)}` não bate com a tabela "
                f"({_nome(esperados[indice])}). "
                "Anote com o tipo do evento, ou tire a anotação."
            )


def _tem_variadic(fn: Handler) -> bool:
    """Se o handler aceita `*args` — aí a validação de aridade não vale."""
    try:
        return any(p.kind is p.VAR_POSITIONAL for p in inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        # Assinatura indisponível (objeto sem `__signature__` útil).
        # Deixa passar: não dá para reclamar de algo que não se vê.
        return True


def _uniao(origem: Any) -> bool:
    """Se a anotação é união — `X | None` (UnionType) ou `Optional[X]`."""
    return origem is types.UnionType or origem is Union


def _compativel(declarado: Any, esperado: Any) -> bool:
    """Se o que o usuário anotou aceita o que a tabela promete.

    União do lado de qualquer um é desmontada: `old: Message | None`
    contra `Message | None` passa, e `old: str | None` contra
    `Message | None` falha porque `str` não entra em nenhuma das pontas.
    """
    if declarado is Any or declarado is object:
        return True

    opcoes = get_args(esperado) if _uniao(get_origin(esperado)) else (esperado,)
    if _uniao(get_origin(declarado)):
        return all(
            any(_compativel(membro, opcao) for opcao in opcoes) for membro in get_args(declarado)
        )
    if not isinstance(declarado, type):
        # Forward ref string, `Callable`, protocolo — não dá para
        # julgar com issubclass, e inventar regra seria mais errado.
        return True
    return any(_subclasse(declarado, opcao) for opcao in opcoes if isinstance(opcao, type))


def _subclasse(declarado: type, esperado: type) -> bool:
    """`issubclass` que não explode com tipos que não formam hierarquia."""
    try:
        return issubclass(declarado, esperado)
    except TypeError:
        return False


def _nome(tipo: Any) -> str:
    """Nome legível de uma anotação, para a mensagem de erro."""
    return getattr(tipo, "__name__", str(tipo))
