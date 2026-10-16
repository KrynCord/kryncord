"""Métricas do cache: acertos, faltas, remoções e tamanho.

`stats.py` separado de `memory.py` porque a métrica não depende de
*como* os dados ficam guardados — uma implementação sobre Redis deveria
reportar as mesmas contas.

Duas regras que o formato impõe:

* **`hit_rate` é `None` quando ninguém consultou.** ``0/0`` não é 0%,
  é "não sei". Devolver ``0.0`` diria que tudo falhou, e um bot olhando
  a métrica concluiria o contrário do que aconteceu.
* **`sizes` não é contador, é estado.** Não zera em `reset()` — apagar
  a contagem de acertos não esvazia o cache.

As contas são por tipo de entidade de propósito. Acerto global alto com
``member`` sempre em falta é um sintoma diferente de cache lento: é
política errada, e só a quebra por tipo revela.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kryncord.cache.keys import CacheKind


@dataclass
class CacheStats:
    """Contadores por tipo de entidade.

    Mutável — é o objeto que a implementação do cache atualiza. Quem só
    lê pega um `snapshot()`, para comparar antes e depois sem ver os
    números mudarem na mão.
    """

    hits: dict[CacheKind, int] = field(default_factory=dict)
    misses: dict[CacheKind, int] = field(default_factory=dict)
    evictions: dict[CacheKind, int] = field(default_factory=dict)
    sizes: dict[CacheKind, int] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Mutadores — só quem guarda chama
    # ------------------------------------------------------------------

    def hit(self, kind: CacheKind) -> None:
        """Registra um acerto."""
        self.hits[kind] = self.hits.get(kind, 0) + 1

    def miss(self, kind: CacheKind) -> None:
        """Registra uma falta — o caminho mais comum, e o que importa."""
        self.misses[kind] = self.misses.get(kind, 0) + 1

    def evict(self, kind: CacheKind, count: int = 1) -> None:
        """Registra remoção por limite de tamanho.

        Conta, não erro: sair do cache por LRU é o sistema funcionando.
        Confundir isso com falha faria alguém desligar o limite — e aí o
        memória cresce sem fim, que é o que o limite existia para evitar.
        """
        if count > 0:
            self.evictions[kind] = self.evictions.get(kind, 0) + count

    def set_size(self, kind: CacheKind, size: int) -> None:
        """Atualiza o tamanho atual de um tipo."""
        self.sizes[kind] = size

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------

    @property
    def total_hits(self) -> int:
        """Acertos em todos os tipos."""
        return sum(self.hits.values())

    @property
    def total_misses(self) -> int:
        """Faltas em todos os tipos."""
        return sum(self.misses.values())

    @property
    def total_evictions(self) -> int:
        """Remoções por limite, em todos os tipos."""
        return sum(self.evictions.values())

    @property
    def total_size(self) -> int:
        """Entradas guardadas, somando todos os tipos."""
        return sum(self.sizes.values())

    @property
    def hit_rate(self) -> float | None:
        """Fração de acertos entre as consultas, ou `None` sem consulta.

        ``None`` e não ``0.0``: nenhuma consulta feita não é nenhuma
        falha. É a diferença entre "o cache não serve" e "ninguém
        perguntou nada ainda".
        """
        accesses = self.total_hits + self.total_misses
        if accesses == 0:
            return None
        return self.total_hits / accesses

    def snapshot(self) -> CacheStats:
        """Cópia independente, para ler sem ver os números mudarem."""
        return CacheStats(
            hits=dict(self.hits),
            misses=dict(self.misses),
            evictions=dict(self.evictions),
            sizes=dict(self.sizes),
        )

    def reset(self) -> None:
        """Zera os contadores.

        `sizes` fica: apagar a contagem de acertos não esvazia o cache,
        e reportar ``size == 0`` logo depois de um `reset()` seria
        mentira sobre quanto está na memória.
        """
        self.hits.clear()
        self.misses.clear()
        self.evictions.clear()
