"""Testes de `kryncord.http.buckets` — descoberta de hash, seeding, sweep."""

from __future__ import annotations

from kryncord.http.buckets import BucketManager, synthetic_hash
from kryncord.http.rate_limits import RateLimitHeaders
from kryncord.http.routes import generate_route_data
from tests.conftest import FakeClock

CHANNEL_A = "123456789012345678"
CHANNEL_B = "987654321098765432"


def _headers(bucket: str, *, remaining: int = 3, reset_after: float = 10.0) -> RateLimitHeaders:
    return RateLimitHeaders(
        limit=5,
        remaining=remaining,
        reset_after=reset_after,
        bucket=bucket,
    )


def _route(path: str):
    return generate_route_data("GET", path)


# --------------------------------------------------------------------------
# Descoberta retroativa
# --------------------------------------------------------------------------


def test_first_request_uses_synthetic_hash() -> None:
    manager = BucketManager()
    route = _route(f"/channels/{CHANNEL_A}")
    bucket = manager.resolve("GET", route)
    assert bucket.key == f"{synthetic_hash('GET', '/channels/:id')}:{CHANNEL_A}"


def test_synthetic_hash_is_never_swept() -> None:
    """Apagá-lo reiniciaria a descoberta a cada varredura."""
    clock = FakeClock()
    manager = BucketManager(clock=clock, hash_lifetime=10.0)
    route = _route(f"/channels/{CHANNEL_A}")
    manager.resolve("GET", route)

    clock.advance(1000.0)
    removed_hashes, _ = manager.sweep()
    assert removed_hashes == []


def test_learn_registers_real_hash() -> None:
    manager = BucketManager()
    route = _route(f"/channels/{CHANNEL_A}")
    manager.resolve("GET", route)
    manager.learn("GET", route, _headers("abc123"))

    assert manager.hashes[BucketManager.hash_key("GET", route)].value == "abc123"


def test_after_learning_new_bucket_is_seeded() -> None:
    """Sem seeding, a segunda requisição partiria de remaining=1 e
    levaria um 429 evitável."""
    clock = FakeClock()
    manager = BucketManager(clock=clock)
    route = _route(f"/channels/{CHANNEL_A}")

    manager.resolve("GET", route)
    manager.learn("GET", route, _headers("abc123", remaining=2, reset_after=7.0))

    bucket = manager.resolve("GET", route)
    assert bucket.key == f"abc123:{CHANNEL_A}"
    assert bucket.state.remaining == 2
    assert bucket.state.bucket_hash == "abc123"
    assert bucket.state.reset_at == clock() + 7.0


def test_learning_twice_keeps_single_hash_entry() -> None:
    manager = BucketManager()
    route = _route(f"/channels/{CHANNEL_A}")
    manager.learn("GET", route, _headers("abc123"))
    manager.learn("GET", route, _headers("abc123"))

    assert len(manager.hashes) == 1


def test_learn_without_hash_header_is_a_noop() -> None:
    """Resposta sem header não pode substituir um hash já conhecido."""
    manager = BucketManager()
    route = _route(f"/channels/{CHANNEL_A}")
    manager.learn("GET", route, _headers("abc123"))
    manager.learn("GET", route, RateLimitHeaders())

    assert manager.hashes[BucketManager.hash_key("GET", route)].value == "abc123"


def test_seeding_does_not_cross_majors() -> None:
    """Regressão crítica: header de `abc:123` não pode irmar o `abc:456`.

    São contadores separados no Discord. Copiar a cota de um para o outro
    faria o cliente achar que tem cota quando não tem (429), ou o
    contrário (fila travada sem motivo).
    """
    manager = BucketManager()
    route_a = _route(f"/channels/{CHANNEL_A}")
    route_b = _route(f"/channels/{CHANNEL_B}")

    manager.learn("GET", route_a, _headers("abc123", remaining=1))
    manager.learn("GET", route_b, _headers("abc123", remaining=4))

    bucket_a = manager.resolve("GET", route_a)
    bucket_b = manager.resolve("GET", route_b)

    assert bucket_a.key != bucket_b.key
    assert bucket_a.state.remaining == 1
    assert bucket_b.state.remaining == 4


def test_same_route_different_channels_share_hash_key() -> None:
    """Major separa instâncias; o *hash* é o mesmo endpoint."""
    manager = BucketManager()
    manager.learn("GET", _route(f"/channels/{CHANNEL_A}"), _headers("abc123"))
    manager.learn("GET", _route(f"/channels/{CHANNEL_B}"), _headers("abc123"))

    keys = set(manager.hashes)
    assert len(keys) == 1


def test_resolve_touches_last_access() -> None:
    """Bucket em uso não pode ser varrido por antiguidade."""
    clock = FakeClock()
    manager = BucketManager(clock=clock, hash_lifetime=100.0)
    route = _route(f"/channels/{CHANNEL_A}")
    manager.learn("GET", route, _headers("abc123"))

    clock.advance(90.0)
    manager.resolve("GET", route)
    clock.advance(90.0)

    removed, _ = manager.sweep()
    assert removed == []


# --------------------------------------------------------------------------
# Sweep
# --------------------------------------------------------------------------


def test_sweep_removes_stale_hashes() -> None:
    clock = FakeClock()
    manager = BucketManager(clock=clock, hash_lifetime=10.0)
    route = _route(f"/channels/{CHANNEL_A}")
    manager.learn("GET", route, _headers("abc123"))

    clock.advance(11.0)
    removed, _ = manager.sweep()
    assert removed == [BucketManager.hash_key("GET", route)]
    assert manager.hashes == {}


def test_sweep_removes_inactive_buckets() -> None:
    clock = FakeClock()
    manager = BucketManager(clock=clock)
    route = _route(f"/channels/{CHANNEL_A}")
    manager.learn("GET", route, _headers("abc123"))
    bucket = manager.resolve("GET", route)

    _, removed = manager.sweep()
    assert removed == [bucket.key]
    assert manager.buckets == {}


def test_sweep_keeps_bucket_with_pending_requests() -> None:
    """Fila cheia nunca é varrida, mesmo antiga — apagaria a espera."""
    manager = BucketManager()
    route = _route(f"/channels/{CHANNEL_A}")
    manager.learn("GET", route, _headers("abc123"))
    bucket = manager.resolve("GET", route)
    bucket.pending = 2

    _, removed = manager.sweep()
    assert removed == []


def test_sweep_keeps_exhausted_bucket() -> None:
    """Bucket sem cota pendente ainda tem estado que importa."""
    clock = FakeClock()
    manager = BucketManager(clock=clock)
    route = _route(f"/channels/{CHANNEL_A}")
    manager.learn("GET", route, _headers("abc123", remaining=0, reset_after=60.0))
    bucket = manager.resolve("GET", route)
    bucket.state.update(_headers("abc123", remaining=0, reset_after=60.0))

    _, removed = manager.sweep()
    assert removed == []


def test_sweep_returns_what_it_removed() -> None:
    """O chamador (e o log) querem saber o que sumiu."""
    clock = FakeClock()
    manager = BucketManager(clock=clock, hash_lifetime=1.0)
    route = _route(f"/channels/{CHANNEL_A}")
    manager.learn("GET", route, _headers("abc123"))
    clock.advance(2.0)

    removed_hashes, removed_buckets = manager.sweep()
    assert len(removed_hashes) == 1
    assert len(removed_buckets) == 1


# --------------------------------------------------------------------------
# Limite global
# --------------------------------------------------------------------------


def test_manager_owns_global_limit() -> None:
    manager = BucketManager(requests_per_second=7)
    assert manager.global_limit.requests_per_second == 7


def test_buckets_start_not_pending() -> None:
    manager = BucketManager()
    bucket = manager.resolve("GET", _route(f"/channels/{CHANNEL_A}"))
    assert bucket.pending == 0
    assert bucket.inactive is True
