"""A instantânea — o `old` lido **antes** do updater mexer no cache.

A ordem do `0025` §4 é o ponto inteiro deste módulo:

```
1. instantânea  -> lê do cache o que o updater vai sobrescrever
2. updater      -> EventUpdater.apply (0008)
3. ready        -> _ready.set() em READY/RESUMED
4. roteamento   -> INTERACTION_CREATE vai aos registries (0026)
5. handlers     -> despacho, com os args montados
```

Ler depois do updater daria `old == new` para sempre, que é o bug que o
`0008` avisou e que ninguém veria: o handler receberia dois objetos
iguais, imprimiria a mesma coisa duas vezes e a diferença que ele
procurava simplesmente não estaria lá.

## Oito eventos pagam

Os mesmos que `monta_args` entrega como `old`. Os outros sete não têm
`old` nenhum, então o `Client` nem chama isto — um `if` vazio no
dispatcher seria o mesmo custo em outro lugar, e pior de ler.

## `state` é anotado como `Any` de propósito

Este módulo lê por contrato (`get_message`, `get_guild`, ...), não por
tipo. Uma anotação de `ConnectionState` real aqui puxaria o `state/`
para dentro do `events/`, e o `events/` é importado pelo `client.py`,
que é quem já conhece o estado. Acoplamento circular por conveniência é
o tipo de coisa que só se paga depois.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kryncord.events.names import normalize_event_name
from kryncord.events.payloads import EVENTOS_COM_OLD, id_de, ids_de

#: O `old` de um `message_delete_bulk`: `id -> mensagem`, ou `id -> None`
#: quando o cache não tinha. Vira tupla alinhada em `monta_args`.
SnapshotBulk = dict[int, Any]


def instantanea(nome: str, data: Any, state: Any) -> Any:
    """O estado do cache para este evento, antes do updater.

    `None` é a resposta padrão — significa "não há o que guardar" (o
    evento não tem `old`, ou o payload não veio como objeto). `None` de
    verdade também acontece: uma mensagem que o cache nunca viu, uma
    guild antes do `GUILD_CREATE`. É o caso legítimo, não uma falha.
    """
    nome = normalize_event_name(nome)
    if nome not in EVENTOS_COM_OLD or not isinstance(data, Mapping):
        return None

    if nome == "message_delete_bulk":
        return _bulk(data, state)

    # Voz vem antes do `id_de`: o payload de `VOICE_STATE_UPDATE` não tem
    # `id` de topo — tem `user_id` — e o `id` nulo cortava a pergunta
    # antes de ela ser feita. O evento pagava snapshot e nunca recebia.
    if nome == "voice_state_update":
        return _voz(data, state)

    codigo = id_de(data)
    if codigo is None:
        return None

    if nome in ("message_update", "message_delete"):
        return state.get_message(codigo)
    if nome in ("guild_update", "guild_delete"):
        return state.get_guild(codigo)
    return state.get_channel(codigo)


def _bulk(data: Mapping[str, Any], state: Any) -> SnapshotBulk:
    """Uma mensagem por id da lista, para o `MESSAGE_DELETE_BULK`.

    Devolve `dict` e não lista porque o `monta_args` precisa casar cada
    mensagem com o seu id — e numa limpeza de canal as mensagens saem
    na ordem dos `ids`, mas nada garante que o cache as devolveu assim.
    """
    return {codigo: state.get_message(codigo) for codigo in ids_de(data)}


def _voz(data: Mapping[str, Any], state: Any) -> Any:
    """O estado de voz anterior de um usuário num guild.

    `guild_id` e `user_id` vêm direto do payload de
    `VOICE_STATE_UPDATE` — voz não existe fora de servidor, e o estado
    é sempre de alguém. Sem os dois, não há para onde perguntar.
    """
    guild_id = _num(data, "guild_id")
    user_id = _num(data, "user_id")
    if guild_id is None or user_id is None:
        return None
    return state.get_voice_state(guild_id, user_id)


def _num(data: Mapping[str, Any], chave: str) -> int | None:
    """Um snowflake do payload como int, ou `None`.

    `bool` é rejeitado antes de `int` por o mesmo motivo de sempre:
    `True` vira o id 1, e um payload com `user_id: true` é payload
    quebrado, não um usuário chamado 1.
    """
    bruto = data.get(chave)
    if isinstance(bruto, str) and bruto.isdigit():
        return int(bruto)
    if isinstance(bruto, int) and not isinstance(bruto, bool):
        return bruto
    return None
