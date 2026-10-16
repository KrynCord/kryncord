"""Agrupamento de rotas nos buckets de rate limit identificados pela API.

Três níveis, cada um com sua chave:

===================================  =========================================
``método:rota generalizada``          → *hash* do bucket (descoberto na resposta)
``hash:major parameter``              → o `Bucket`, dono do contador
===================================  =========================================

**Por que dois níveis.** ``/channels/123/messages`` e
``/channels/456/messages`` caem no mesmo hash — mesmo endpoint, mesma
regra. Mas o Discord conta *por servidor*: o 123 e o 456 têm janelas
separadas. Misturar os dois daria um falso 429 de um no outro.

**Descoberta retroativa.** Antes da primeira resposta não sabemos o hash;
usamos um sintético (``Global(...)``). Quando ``X-RateLimit-Bucket``
chega, registramos o mapeamento — e, se o bucket de destino ainda não
existe, criamos já **semeado** com os headers observados. Sem o
semeamento, a segunda requisição partiria de `remaining = 1` e levaria um
429 evitável.

Semeamos só na criação, e sempre com o major da requisição que observou.
Copiar header de ``abc:123`` para ``abc:456`` corromperia a cota do 456 —
são contadores distintos.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from kryncord.http.rate_limits import (
    BucketState,
    Clock,
    GlobalRateLimit,
    RateLimitHeaders,
    monotonic_clock,
)
from kryncord.http.routes import RouteData

#: Hash usado enquanto o Discord não revelou o real. Nunca é varrido:
#: apagá-lo reiniciaria a descoberta a cada varredura.
SYNTHETIC_PREFIX = "Global("


def synthetic_hash(method: str, bucket_route: str) -> str:
    """Hash provisório: o Discord ainda não disse qual é o verdadeiro."""
    return f"{SYNTHETIC_PREFIX}{method}:{bucket_route})"


@dataclass(frozen=True, slots=True)
class HashEntry:
    """Mapeamento ``método:rota → hash``, com o último acesso."""

    value: str
    last_access: float
    sweepable: bool = True


@dataclass(slots=True)
class Bucket:
    """Um contador de rate limit: estado + exclusão mútua."""

    key: str
    """``hash:major``."""

    state: BucketState
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: int = 0
    """Requisições segurando ou esperando este bucket. É isto que define
    `inactive` — sem contar, o sweeper apagaria bucket com fila cheia."""

    @property
    def inactive(self) -> bool:
        return self.pending == 0 and not self.state.exhausted

    def __repr__(self) -> str:
        return f"Bucket({self.key!r}, {self.state.snapshot()})"


class BucketManager:
    """Dono dos mapeamentos rota→hash→bucket, e do limite global."""

    def __init__(
        self,
        *,
        requests_per_second: int = 50,
        clock: Clock = monotonic_clock,
        hash_lifetime: float = 86_400.0,
    ) -> None:
        self._clock = clock
        self.hashes: dict[str, HashEntry] = {}
        self.buckets: dict[str, Bucket] = {}
        self.global_limit = GlobalRateLimit(requests_per_second=requests_per_second, clock=clock)
        self._hash_lifetime = hash_lifetime

    # ------------------------------------------------------------------
    # Resolução
    # ------------------------------------------------------------------

    def resolve(self, method: str, route: RouteData) -> Bucket:
        """Bucket que atende esta requisição, criando se preciso."""
        key = self.hash_key(method, route)
        entry = self.hashes.get(key)

        if entry is None:
            bucket_hash = synthetic_hash(method, route.bucket_route)
        else:
            # Toca o acesso para o sweeper não matar bucket em uso.
            self.hashes[key] = HashEntry(
                value=entry.value,
                last_access=self._clock(),
                sweepable=entry.sweepable,
            )
            bucket_hash = entry.value

        return self._bucket_for(bucket_hash, route.major_parameter)

    def learn(self, method: str, route: RouteData, headers: RateLimitHeaders) -> None:
        """Registra o hash que a resposta revelou, e semeia se for novo.

        Chamado após **cada** resposta — o Discord manda
        ``X-RateLimit-Bucket`` sempre, não só no 429.
        """
        if headers.bucket is None:
            return

        key = self.hash_key(method, route)
        self.hashes[key] = HashEntry(value=headers.bucket, last_access=self._clock())

        target_key = self.bucket_key(headers.bucket, route.major_parameter)
        if target_key not in self.buckets:
            bucket = Bucket(key=target_key, state=BucketState(clock=self._clock))
            bucket.state.update(headers)
            self.buckets[target_key] = bucket

    def _bucket_for(self, bucket_hash: str, major: str) -> Bucket:
        key = self.bucket_key(bucket_hash, major)
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = Bucket(key=key, state=BucketState(clock=self._clock))
            self.buckets[key] = bucket
        return bucket

    # ------------------------------------------------------------------
    # Chaves
    # ------------------------------------------------------------------

    @staticmethod
    def hash_key(method: str, route: RouteData) -> str:
        return f"{method}:{route.bucket_route}"

    @staticmethod
    def bucket_key(bucket_hash: str, major: str) -> str:
        return f"{bucket_hash}:{major}"

    # ------------------------------------------------------------------
    # Varredura
    # ------------------------------------------------------------------

    def sweep(self) -> tuple[list[str], list[str]]:
        """Remove hashes e buckets ociosos. Devolve o que foi removido.

        Só sai o que está **inativo**: `pending == 0` e sem cota pendente.
        Um bucket com fila cheia nunca é varrido, mesmo antigo.
        """
        now = self._clock()
        removed_hashes = [key for key, entry in self.hashes.items() if self._stale(entry, now)]
        removed_buckets = [key for key, bucket in self.buckets.items() if bucket.inactive]

        for key in removed_hashes:
            del self.hashes[key]
        for key in removed_buckets:
            del self.buckets[key]

        return removed_hashes, removed_buckets

    def _stale(self, entry: HashEntry, now: float) -> bool:
        if not entry.sweepable:
            return False
        return (now - entry.last_access) > self._hash_lifetime
