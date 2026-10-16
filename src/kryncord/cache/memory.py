"""Cache em memória: `OrderedDict` por tipo, teto LRU e índice por guild.

## Por que `_Entry`

O valor guardado carrega junto a guild de que veio (`group`). Parece
dispensável — o índice de grupos já sabe —, mas é o contrário: na hora
de **remover**, seja por `pop` seja por LRU, é preciso descobrir de
qual índice tirar a chave. Sem o `group` junto, restariam duas saídas,
e as duas são ruins:

- guardar `key → group` num dict separado: cada entrada ganha um slot
  de hash novo, e para cem mil membros isso custa mais que o próprio
  objeto;
- varrer todos os grupos procurando a chave: O(nº de guilds) em cada
  remoção, pagando por toda guild de cada mensagem que sai.

`NamedTuple` resolve com um campo a mais no valor que já ia lá — sem
slot de hash novo, e `entry.group` é direto.

## LRU e o `move_to_end`

`get()` promove a entrada no tipos com teto. É o que faz "os 5000
últimos usuários vistos" significar os *vistos*, e não os *inseridos* —
sem a promoção, um autor que fala todo dia seria descartado por alguém
que passou uma vez e nunca mais apareceu.

Só nos tipos com teto. Num tipo sem teto a promoção é trabalho que não
muda nada, e `move_to_end` não é de graça.

## Ordem

`OrderedDict` e não `dict`: `dict` preserva inserção desde 3.7, mas não
tem `move_to_end` nem `popitem(last=False)`. LRU é justamente isso —
`dict` comum não dá para implementar sem reescrever a ordem inteira.

A ordem de `group_values()` é a de inserção, que para membro é a ordem
em que o gateway entregou. Não há ordem natural: o Discord não manda
"membros em algum ordem", manda um array que pode vir em qualquer.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, NamedTuple

from kryncord.cache.keys import CacheKind
from kryncord.cache.policy import CachePolicy
from kryncord.cache.stats import CacheStats


class _Entry(NamedTuple):
    """Um valor guardado e a guild de que veio (`None` quando não veio de guild)."""

    value: Any
    group: str | None


class MemoryCache:
    """Implementação em memória, com a política decidindo o que entra.

    Conforme `protocol.CacheProtocol` — é a trocável por uma outra,
    desde que cumpra os mesmos métodos.
    """

    __slots__ = ("_groups", "_policy", "_stats", "_stores")

    def __init__(self, policy: CachePolicy | None = None) -> None:
        self._policy = policy if policy is not None else CachePolicy()
        #: Um `OrderedDict` por tipo. Cria sob demanda: sete tipos e a
        #: maioria dos bots usa três, sete dicts vazios seria desperdício.
        self._stores: dict[CacheKind, OrderedDict[str, _Entry]] = {}
        #: `tipo → grupo → chaves`. Apenas os tipos que têm grupo
        #: (membro, cargo, canal) entram aqui.
        self._groups: dict[CacheKind, dict[str, dict[str, None]]] = {}
        self._stats = CacheStats()

    # ------------------------------------------------------------------
    # CacheProtocol
    # ------------------------------------------------------------------

    @property
    def policy(self) -> CachePolicy:
        """A política que esta implementação obedece."""
        return self._policy

    @property
    def stats(self) -> CacheStats:
        """Cópia das métricas, com os tamanhos atualizados.

        Cópia de propósito: quem guarda um `CacheStats` para comparar
        antes e depois não pode ver os números mudarem dentro do objeto
        que achava ser um retrato.
        """
        snapshot = self._stats.snapshot()
        for kind, store in self._stores.items():
            snapshot.sizes[kind] = len(store)
        return snapshot

    def get(self, kind: CacheKind, key: str) -> Any | None:
        """Devolve o valor, promovendo-a no LRU quando o tipo tem teto.

        Falta conta como falta mesmo quando a política desligou o tipo:
        quem chamou `get_member()` recebeu `None`, e a métrica tem que
        dizer isso.
        """
        store = self._stores.get(kind)
        if store is None:
            self._stats.miss(kind)
            return None
        entry = store.get(key)
        if entry is None:
            self._stats.miss(kind)
            return None
        if self._policy.limit_for(kind) is not None:
            store.move_to_end(key)
        self._stats.hit(kind)
        return entry.value

    def set(self, kind: CacheKind, key: str, value: Any, *, group: str | None = None) -> None:
        """Guarda, ou ignora se a política desligou o tipo.

        Ignorar é o contrato: a política é quem decide, e um `set` que
        desligasse a política por baixo tornaria `CachePolicy` uma
        sugestão.
        """
        if not self._policy.allows(kind):
            return

        store = self._stores.setdefault(kind, OrderedDict())
        anterior = store.get(key)
        if anterior is not None and anterior.group != group:
            # Estava em outro grupo — mover de índice. Trocar a guild de
            # um canal não deixa a chave órfã no índice antigo, que seria
            # um membro que aparece na guild de antes para sempre.
            self._unindex(kind, key, anterior.group)

        store[key] = _Entry(value, group)
        if group is not None:
            grupos = self._groups.setdefault(kind, {})
            grupos.setdefault(group, {})[key] = None

        limite = self._policy.limit_for(kind)
        if limite is not None:
            store.move_to_end(key)
            self._evict_to(kind, limite)

        self._sync_size(kind)

    def pop(self, kind: CacheKind, key: str) -> Any | None:
        """Remove e devolve.

        Sem conta de falta quando não existia — `MESSAGE_DELETE` de
        mensagem nunca cacheada é o caso normal, e puni-lo como falha
        faria a métrica culpar o cache por ele estar incompleto, que é
        o estado dele por design.
        """
        store = self._stores.get(kind)
        if store is None:
            return None
        entry = store.pop(key, None)
        if entry is None:
            return None
        self._unindex(kind, key, entry.group)
        self._sync_size(kind)
        return entry.value

    def values(self, kind: CacheKind) -> tuple[Any, ...]:
        """Todos os valores do tipo, do menos ao mais recentemente usado."""
        store = self._stores.get(kind)
        if not store:
            return ()
        return tuple(entry.value for entry in store.values())

    def group_values(self, kind: CacheKind, group: str) -> tuple[Any, ...]:
        """Valores do tipo dentro de uma guild, em ordem de chegada."""
        chaves = self._groups.get(kind, {}).get(group)
        if not chaves:
            return ()
        store = self._stores.get(kind)
        if store is None:
            return ()
        valores: list[Any] = []
        for key in chaves:
            entry = store.get(key)
            if entry is not None:
                valores.append(entry.value)
        return tuple(valores)

    def clear(self, kind: CacheKind | None = None) -> None:
        """Esvazia um tipo, ou tudo.

        Os contadores ficam: apagar os dados não apaga o histórico de
        acertos. `stats.sizes` acompanha — `size` reflete o cache
        *agora*, então é o único campo que `reset()` não zera e este
        método zera sim.
        """
        alvos = (kind,) if kind is not None else tuple(CacheKind)
        for alvo in alvos:
            self._stores.pop(alvo, None)
            self._groups.pop(alvo, None)
            self._stats.set_size(alvo, 0)

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    def _evict_to(self, kind: CacheKind, limite: int) -> None:
        """Derruba pelo menos os menos recentes até caber no teto.

        `while` e não `if`: o teto pode ter caído entre uma rodada e
        outra (política trocada num cliente novo), e uma entrada por
        rodada não estaria de pé quando a diferença é grande.
        """
        store = self._stores.get(kind)
        if store is None:
            return
        while len(store) > limite:
            key, entry = store.popitem(last=False)
            self._unindex(kind, key, entry.group)
            self._stats.evict(kind)

    def _unindex(self, kind: CacheKind, key: str, group: str | None) -> None:
        """Tira a chave do índice do grupo dela."""
        if group is None:
            return
        grupos = self._groups.get(kind)
        if grupos is None:
            return
        chaves = grupos.get(group)
        if chaves is not None:
            chaves.pop(key, None)
            if not chaves:
                # Grupo vazio não fica: um servidor que o bot saiu não
                # pode deixar um `set` vazio no índice, que seria
                # memória e uma ordem fantasma para sempre.
                grupos.pop(group, None)

    def _sync_size(self, kind: CacheKind) -> None:
        """Mantém `stats.sizes` igual ao store, sem esperar consulta."""
        store = self._stores.get(kind)
        self._stats.set_size(kind, 0 if store is None else len(store))
