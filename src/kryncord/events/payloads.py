"""`EVENT_PAYLOADS` — a assinatura que o handler de cada evento recebe.

São **duas** tabelas vivendo juntas, e elas não se duplicam porque
respondem perguntas diferentes (o mesmo argumento do `0020`):

| Tabela | Quem | O quê |
|---|---|---|
| `REGISTRY` (0006) | parser do payload cru | evento → **um** objeto interpretado |
| `EVENT_PAYLOADS` (0020) | assinatura do handler | evento → **tupla de argumentos** |

Para `message_create` as duas coincidem: o parser devolve `Message`, e a
tupla é `(Message,)`. Para `message_update` divergem — o parser continua
devolvendo o `Message` novo, e a tupla é `(old, new)`. Para
`message_delete` nem o parser entra: o argumento é o `id`, que vem do
payload, e o `old`, que vem do cache antes do updater.

## Correção do `0020`

A decisão original escrevia `ready -> ()` e `resumed -> ()`. Isso faria
`client.on("READY")` receber **zero** argumentos, anulando o `0006`
("`READY` vira `Ready`"), o teste `test_ready_vira_modelo` e o smoke test
do `bot testes/main.py`. Prevalece o `0006`; a correção está registrada
em `0025` §2.

## A aridade é o contrato; o tipo é a promessa

Quando o parser falha, o payload cru ocupa a **posição** do modelo —
nunca muda a quantidade de argumentos no meio do dispatch. `TypeError`
de argumento faltando mascararia o erro verdadeiro do parser, e é o
tipo de falha que ninguém acha lendo a pilha.

Ver `0025` para as alternativas consideradas.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from kryncord.events.names import normalize_event_name
from kryncord.models.channel import Channel
from kryncord.models.guild import Guild
from kryncord.models.interaction import Interaction
from kryncord.models.message import Message
from kryncord.models.ready import Ready
from kryncord.models.typing import TypingStart
from kryncord.models.voice import VoiceState

#: Evento → tipos dos argumentos que o handler recebe, na ordem.
#:
#: Só os quinze que o `0020` listou — "a tabela cresce com o que a
#: biblioteca já sabe parsear". Adicionar um dezesseis sem parser seria
#: prometer um tipo que ninguém entrega.
EVENT_PAYLOADS: dict[str, tuple[Any, ...]] = {
    "ready": (Ready,),
    "resumed": (Mapping[str, Any],),
    "message_create": (Message,),
    "message_update": (Message | None, Message),
    "message_delete": (int, Message | None),
    "message_delete_bulk": (tuple[int, ...], tuple[Message | None, ...]),
    "interaction_create": (Interaction,),
    "guild_create": (Guild,),
    "guild_update": (Guild | None, Guild),
    "guild_delete": (int, Guild | None),
    "channel_create": (Channel,),
    "channel_update": (Channel | None, Channel),
    "channel_delete": (int, Channel | None),
    "typing_start": (TypingStart,),
    "voice_state_update": (VoiceState | None, VoiceState),
}


class PayloadShape(StrEnum):
    """Quantos argumentos o evento entrega, e de onde vêm.

    Cinco formas porque são cinco. O `0025` §4 escreveu-as como tabela e
    decidiu que elas são código, não comentário: é o que permite a
    aridade ficar estável quando o parser falha.
    """

    #: `ready`, `resumed` — nenhum argumento além do contexto.
    EMPTY = "empty"

    #: `message_create` — o objeto interpretado, sozinho.
    SINGLE = "single"

    #: `message_update` — o `old` do cache, depois o `new` interpretado.
    OLD_NEW = "old_new"

    #: `message_delete` — o `id` do payload, depois o `old` do cache.
    ID_OLD = "id_old"

    #: `message_delete_bulk` — os `ids` do payload, depois os `olds`.
    IDS_OLDS = "ids_olds"


#: Forma de cada evento. Só os quinze de `EVENT_PAYLOADS`.
_FORMAS: dict[str, PayloadShape] = {
    "ready": PayloadShape.SINGLE,
    "resumed": PayloadShape.SINGLE,
    "message_create": PayloadShape.SINGLE,
    "message_update": PayloadShape.OLD_NEW,
    "message_delete": PayloadShape.ID_OLD,
    "message_delete_bulk": PayloadShape.IDS_OLDS,
    "interaction_create": PayloadShape.SINGLE,
    "guild_create": PayloadShape.SINGLE,
    "guild_update": PayloadShape.OLD_NEW,
    "guild_delete": PayloadShape.ID_OLD,
    "channel_create": PayloadShape.SINGLE,
    "channel_update": PayloadShape.OLD_NEW,
    "channel_delete": PayloadShape.ID_OLD,
    "typing_start": PayloadShape.SINGLE,
    "voice_state_update": PayloadShape.OLD_NEW,
}

#: Os eventos que pagam a instantânea do cache (`0025` §4) — os que
#: entregam um `old`. Os outros sete pagam um `if` vazio.
EVENTOS_COM_OLD: frozenset[str] = frozenset(
    nome
    for nome, forma in _FORMAS.items()
    if forma in (PayloadShape.OLD_NEW, PayloadShape.ID_OLD, PayloadShape.IDS_OLDS)
)


def forma_de(nome: str) -> PayloadShape | None:
    """A forma de um evento, ou `None` se ele não está na tabela.

    `None` é o caso do evento sem parser, que chega cru com um único
    argumento — comportamento do `0006`, que não muda porque uma tabela
    nova passou a existir.
    """
    return _FORMAS.get(normalize_event_name(nome))


def usa_parsed(nome: str) -> bool:
    """Se o parser do `REGISTRY` tem algo a acrescentar a este evento.

    `message_delete` e `message_delete_bulk` montam os argumentos só a
    partir do payload e do cache — chamar o parser seria custo que não
    vira argumento nenhum.
    """
    forma = forma_de(nome)
    if forma is None:
        return True
    return forma in (PayloadShape.SINGLE, PayloadShape.OLD_NEW)


def monta_args(
    nome: str,
    parsed: Any,
    old: Any,
    data: Any,
) -> tuple[Any, ...]:
    """Os argumentos finais do evento, na ordem da `EVENT_PAYLOADS`.

    `parsed` é o que o `REGISTRY` devolveu (ou o payload cru, pela
    tolerância do `0006`), `old` é a instantânea lida **antes** do
    updater, e `data` é o payload original — do qual ainda saem o `id`
    e os `ids`, que não passam por modelo nenhum.

    Evento fora da tabela devolve `(parsed,)`: é o comportamento do
    `0006` para o que não tem parser, e trocar isso porque uma tabela
    nova apareceu seria quebrar o que funcionava.
    """
    nome = normalize_event_name(nome)
    forma = _FORMAS.get(nome)
    if forma is None:
        return (parsed,)

    if forma is PayloadShape.EMPTY:
        return ()
    if forma is PayloadShape.SINGLE:
        return (parsed,)
    if forma is PayloadShape.OLD_NEW:
        return (old, parsed)
    if forma is PayloadShape.ID_OLD:
        return (id_de(data), old)
    # IDS_OLDS: `olds` alinhado por índice aos `ids` — `dict(zip(ids,
    # olds))` funciona, e `None` marca a que o cache não tinha. Filtrar
    # perderia a informação de qual faltou (`0025` §Quebras).
    ids = ids_de(data)
    return (ids, alinhados(ids, old))


def id_de(data: Any) -> int | None:
    """O `id` do payload como int, tolerante.

    Aceita ``"123"`` e `123`; qualquer outra coisa devolve `None`. Um
    payload sem `id` não derruba o dispatch — chega `None` no lugar, e o
    handler decide o que fazer com um id que não veio.
    """
    if not isinstance(data, Mapping):
        return None
    bruto = data.get("id")
    if isinstance(bruto, str) and bruto.isdigit():
        return int(bruto)
    if isinstance(bruto, int) and not isinstance(bruto, bool):
        return bruto
    return None


def ids_de(data: Any) -> tuple[int, ...]:
    """Os `ids` de um `MESSAGE_DELETE_BULK`, como tupla de int.

    Só os que parecem snowflake: um item quebrado dentro da lista é
    descartado, não derruba o resto — as mensagens boas ainda podem ser
    apagadas do cache.
    """
    if not isinstance(data, Mapping):
        return ()
    bruto = data.get("ids")
    if not isinstance(bruto, list):
        return ()
    saida: list[int] = []
    for item in bruto:
        if isinstance(item, str) and item.isdigit():
            saida.append(int(item))
        elif isinstance(item, int) and not isinstance(item, bool):
            saida.append(item)
    return tuple(saida)


def alinhados(ids: tuple[int, ...], old: Any) -> tuple[Any, ...]:
    """Os `olds` na mesma ordem dos `ids`, com `None` onde faltou.

    A instantânea de `message_delete_bulk` devolve um `dict` de id →
    mensagem; aqui ele vira tupla alinhada. Sem isso, `zip(ids, olds)`
    casaria a mensagem errada com o id errado — e "qual mensagem foi
    apagada?" é a única pergunta que este evento existe para responder.
    """
    if isinstance(old, Mapping):
        return tuple(old.get(codigo) for codigo in ids)
    if isinstance(old, (list, tuple)):
        return tuple(old)
    return tuple(None for _ in ids)
