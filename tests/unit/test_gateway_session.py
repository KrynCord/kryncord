"""Testes de `kryncord.gateway.session` — o que precisa sobreviver à queda.

Sessão é a única coisa que transforma uma reconexão em "ninguém percebeu"
em vez de "o bot voltou do zero". Os testes aqui cobrem o parsing do
``READY`` (que **não** derruba a conexão quando falta campo) e a regra de
topologia, que é a menos óbvia: se o número de shards mudou, a sessão
antiga pertence a uma divisão que já não existe.
"""

from __future__ import annotations

import pytest

from kryncord.gateway.session import InMemorySessionStore, SessionInfo

READY_BODY = {
    "session_id": "sessao-abc123",
    "resume_gateway_url": "wss://us-central1-b.discord.gg",
    "user": {"id": "1", "username": "prova"},
}


def _info(**overrides: object) -> SessionInfo:
    base: dict[str, object] = {
        "session_id": "sessao-abc123",
        "sequence": 7,
        "resume_url": "wss://us-central1-b.discord.gg",
        "shard_id": 0,
        "shard_count": 1,
    }
    base.update(overrides)
    return SessionInfo(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# from_dispatch — o parsing do READY
# --------------------------------------------------------------------------


def test_from_dispatch_extracts_the_three_fields() -> None:
    session = SessionInfo.from_dispatch(READY_BODY, sequence=7, shard_id=0, shard_count=1)

    assert session is not None
    assert session.session_id == "sessao-abc123"
    assert session.sequence == 7
    assert session.resume_url == "wss://us-central1-b.discord.gg"


def test_from_dispatch_returns_none_instead_of_raising() -> None:
    """`READY` sem `session_id` é anomalia do Discord, não erro nosso.

    Derrubar a conexão inteira por isso troca um problema contornável
    (identify novo) por um fatal.
    """
    assert SessionInfo.from_dispatch({}, sequence=1, shard_id=0, shard_count=1) is None


@pytest.mark.parametrize(
    "body",
    [
        {"session_id": "abc"},  # sem resume_gateway_url
        {"resume_gateway_url": "wss://x"},  # sem session_id
        {"session_id": 5, "resume_gateway_url": "wss://x"},  # tipo errado
        {"session_id": "abc", "resume_gateway_url": 7},  # tipo errado
    ],
)
def test_from_dispatch_rejects_incomplete_bodies(body: dict[str, object]) -> None:
    assert SessionInfo.from_dispatch(body, sequence=1, shard_id=0, shard_count=1) is None


# --------------------------------------------------------------------------
# can_resume_with — a regra de topologia
# --------------------------------------------------------------------------


def test_session_survives_same_shard_count() -> None:
    assert _info(shard_count=4).can_resume_with(4) is True


def test_session_dies_when_topology_changes() -> None:
    """Mudou o número de shards? A sessão antiga é de outra divisão."""
    assert _info(shard_count=4).can_resume_with(5) is False
    assert _info(shard_count=1).can_resume_with(2) is False


# --------------------------------------------------------------------------
# from_ready — o construtor direto
# --------------------------------------------------------------------------


def test_from_ready_is_a_plain_constructor() -> None:
    session = SessionInfo.from_ready(
        session_id="abc",
        sequence=3,
        resume_url="wss://x.discord.gg",
        shard_id=2,
        shard_count=8,
    )
    assert session.shard_id == 2
    assert session.shard_count == 8


# --------------------------------------------------------------------------
# InMemorySessionStore
# --------------------------------------------------------------------------


async def test_store_round_trip() -> None:
    store = InMemorySessionStore()
    assert await store.retrieve(0) is None

    session = _info()
    await store.update(0, session)

    assert await store.retrieve(0) == session
    assert len(store) == 1
    assert 0 in store


async def test_store_clearing_is_idempotent() -> None:
    """Apagar sessão que não existe não levanta — o shutdown roda duas vezes."""
    store = InMemorySessionStore()
    await store.update(0, _info())
    await store.update(0, None)
    await store.update(0, None)

    assert await store.retrieve(0) is None
    assert len(store) == 0
    assert 0 not in store


async def test_store_keeps_shards_apart() -> None:
    store = InMemorySessionStore()
    await store.update(0, _info(shard_id=0))
    await store.update(1, _info(shard_id=1, session_id="outro"))

    await store.update(0, None)

    # Zerar uma shard não pode apagar a vizinha.
    assert await store.retrieve(1) is not None
    assert (await store.retrieve(1)).session_id == "outro"  # type: ignore[union-attr]


def test_empty_store_is_falsy() -> None:
    """Isso é uma armadilha documentada: `store or InMemorySessionStore()`
    descartaria um store customizado recém-criado em silêncio."""
    store = InMemorySessionStore()
    assert not store
    assert bool(store) is False
