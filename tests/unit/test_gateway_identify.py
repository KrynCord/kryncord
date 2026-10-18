"""Testes de `kryncord.gateway.identify` — o payload e o teto de sessões.

Dois assuntos que parecem separados e não são: os dois respondem a
"como apresentar este bot ao Discord sem ser derrubado".

Os erros de argumento viram `ValueError`, não `DefinitionError` — o
contrato do segundo é "detectado na importação", e identify é chamado em
`start()`, quando o usuário ainda pode corrigir a mensagem.
"""

from __future__ import annotations

import asyncio

import pytest

from kryncord.enums import GatewayOpcode
from kryncord.gateway.identify import (
    IDENTIFY_INTERVAL,
    MAX_LARGE_THRESHOLD,
    MIN_LARGE_THRESHOLD,
    IdentifyProperties,
    IdentifyThrottler,
    build_identify,
    build_resume,
)
from tests.conftest import FakeClock, FakeSleeper

# --------------------------------------------------------------------------
# build_identify
# --------------------------------------------------------------------------


def test_identify_carries_token_intents_and_properties() -> None:
    payload = build_identify(
        token="meu-token",
        intents=512,
        properties=IdentifyProperties(os="linux", browser="kryncord", device="kryncord"),
    )

    assert payload.op == GatewayOpcode.IDENTIFY
    assert payload.data["token"] == "meu-token"
    assert payload.data["intents"] == 512
    assert payload.data["properties"] == {
        "os": "linux",
        "browser": "kryncord",
        "device": "kryncord",
    }


def test_payload_compression_stays_off_by_default() -> None:
    """Dois níveis de compressão, e este é o errado para ligar por padrão.

    O que interessa é o de transporte, que vai na query da URL. Ligar
    este aqui comprimiria cada mensagem isoladamente, sem ganho, e com
    um estado a mais para dar errado.
    """
    payload = build_identify(token="t", intents=1)
    assert payload.data["compress"] is False


def test_identify_manda_capabilities_zero() -> None:
    """`capabilities: 0` é o default documentado da API — e é o que o
    discord.js envia sempre. Mandar explícito é paridade pura: se o
    default da API mudar, quem manda o campo continua recebendo o
    comportamento de hoje."""
    payload = build_identify(token="t", intents=1)
    assert payload.data["capabilities"] == 0


def test_properties_accept_a_plain_mapping() -> None:
    payload = build_identify(token="t", intents=1, properties={"os": "windows"})
    assert payload.data["properties"] == {"os": "windows"}


def test_shard_is_omitted_for_a_single_shard() -> None:
    """Mandar ``shard: [0, 1]`` é inofensivo, mas o campo existe para
    shards de verdade — omitir mantém o payload do caso comum limpo."""
    payload = build_identify(token="t", intents=1)
    assert "shard" not in payload.data


def test_shard_is_sent_as_a_pair_when_sharded() -> None:
    payload = build_identify(token="t", intents=1, shard=(2, 8))
    assert payload.data["shard"] == [2, 8]


def test_optional_fields_are_omitted_not_null() -> None:
    payload = build_identify(token="t", intents=1)
    assert "large_threshold" not in payload.data
    assert "presence" not in payload.data


def test_optional_fields_are_sent_when_given() -> None:
    payload = build_identify(
        token="t", intents=1, large_threshold=100, presence={"since": None, "status": "idle"}
    )
    assert payload.data["large_threshold"] == 100
    assert payload.data["presence"]["status"] == "idle"


# --------------------------------------------------------------------------
# build_identify — recusas
# --------------------------------------------------------------------------


def test_empty_token_is_rejected() -> None:
    with pytest.raises(ValueError, match="token"):
        build_identify(token="   ", intents=1)


@pytest.mark.parametrize("intents", [-1, 1.5, "512", True])
def test_invalid_intents_are_rejected(intents: object) -> None:
    """``True`` é `int` em Python — e mandaria intents=1 por engano."""
    with pytest.raises(ValueError, match="intents"):
        build_identify(token="t", intents=intents)  # type: ignore[arg-type]


@pytest.mark.parametrize("threshold", [MIN_LARGE_THRESHOLD - 1, MAX_LARGE_THRESHOLD + 1])
def test_large_threshold_outside_the_api_range_is_rejected(threshold: int) -> None:
    """O Discord descarta o identify fora de 50–256, e o close code que
    vem depois não aponta o threshold como suspeito."""
    with pytest.raises(ValueError, match="large_threshold"):
        build_identify(token="t", intents=1, large_threshold=threshold)


def test_large_threshold_bounds_are_accepted() -> None:
    low = build_identify(token="t", intents=1, large_threshold=MIN_LARGE_THRESHOLD)
    high = build_identify(token="t", intents=1, large_threshold=MAX_LARGE_THRESHOLD)
    assert low.data["large_threshold"] == MIN_LARGE_THRESHOLD
    assert high.data["large_threshold"] == MAX_LARGE_THRESHOLD


@pytest.mark.parametrize("shard", [(5, 4), (-1, 4), (0, 0)])
def test_invalid_shard_pair_is_rejected(shard: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="shard"):
        build_identify(token="t", intents=1, shard=shard)


def test_rejected_identify_never_builds_a_payload() -> None:
    """Validação antes de montar: um payload meio-errado não pode vazar."""
    with pytest.raises(ValueError):
        build_identify(token="", intents=-1)


# --------------------------------------------------------------------------
# build_resume
# --------------------------------------------------------------------------


def test_resume_carries_the_three_fields() -> None:
    payload = build_resume(token="t", session_id="sessao-1", sequence=42)

    assert payload.op == GatewayOpcode.RESUME
    assert payload.data == {"token": "t", "session_id": "sessao-1", "seq": 42}


def test_resume_without_session_id_is_rejected() -> None:
    """Sem `session_id` não há o que retomar — identify novo resolve."""
    with pytest.raises(ValueError, match="session_id"):
        build_resume(token="t", session_id="", sequence=1)


def test_resume_with_negative_sequence_is_rejected() -> None:
    with pytest.raises(ValueError, match="sequence"):
        build_resume(token="t", session_id="s", sequence=-1)


def test_resume_accepts_sequence_zero() -> None:
    """Zero é a primeira sequence possível, não um valor ausente."""
    assert build_resume(token="t", session_id="s", sequence=0).data["seq"] == 0


# --------------------------------------------------------------------------
# IdentifyThrottler
# --------------------------------------------------------------------------


async def _drain() -> None:
    """Dá ao throttler a chance de rodar, sem dormir de verdade."""
    for _ in range(50):
        await asyncio.sleep(0)


def _throttler(clock: FakeClock, sleeper: FakeSleeper, **kwargs: object) -> IdentifyThrottler:
    kwargs.setdefault("random", lambda: 0.0)
    return IdentifyThrottler(clock=clock, sleeper=sleeper, **kwargs)  # type: ignore[arg-type]


async def test_first_identify_is_immediate(clock: FakeClock, sleeper: FakeSleeper) -> None:
    throttler = _throttler(clock, sleeper)

    await throttler.wait(0)
    await _drain()

    assert sleeper.calls == []
    assert throttler.seconds_until_next(0) == pytest.approx(IDENTIFY_INTERVAL)


async def test_second_identify_waits_for_the_window(clock: FakeClock, sleeper: FakeSleeper) -> None:
    throttler = _throttler(clock, sleeper)

    await throttler.wait(0)
    clock.advance(2.0)
    await throttler.wait(0)
    await _drain()

    # Faltavam 3s da janela de 5s, e o jitter está zerado no teste.
    assert sleeper.calls == [pytest.approx(3.0)]
    # Dormir avança o relógio falso: a janela já virou.
    assert throttler.seconds_until_next(0) == pytest.approx(IDENTIFY_INTERVAL)


async def test_expired_window_does_not_sleep(clock: FakeClock, sleeper: FakeSleeper) -> None:
    throttler = _throttler(clock, sleeper)

    await throttler.wait(0)
    clock.advance(IDENTIFY_INTERVAL + 1.0)
    await throttler.wait(0)
    await _drain()

    # A primeira chamada é imediata; a segunda encontra a janela já
    # vencida pelo relógio, então nenhuma das duas dorme.
    assert sleeper.calls == []


async def test_jitter_is_added_to_the_wait(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """A folga existe porque o identify atravessa a rede. Errar para o
    lado da espera custa 1,5s; errar para o lado do envio custa 4008."""
    throttler = IdentifyThrottler(clock=clock, sleeper=sleeper, random=lambda: 1.0, jitter=1.5)

    await throttler.wait(0)
    await throttler.wait(0)
    await _drain()

    assert sleeper.calls == [pytest.approx(IDENTIFY_INTERVAL + 1.5)]


async def test_shards_in_different_buckets_are_independent(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """O bucket é ``shard_id % max_concurrency`` — a divisão do Discord.

    Shard 0 e shard 1 com `max_concurrency=2` não competem: as duas
    identificam de primeira.
    """
    throttler = _throttler(clock, sleeper, max_concurrency=2)

    await throttler.wait(0)
    await throttler.wait(1)
    await _drain()

    assert sleeper.calls == []


async def test_same_bucket_shards_queue_up(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """``max_concurrency=1``: todo identify divide o mesmo teto."""
    throttler = _throttler(clock, sleeper, max_concurrency=4)

    await throttler.wait(0)
    await throttler.wait(4)  # 4 % 4 == 0, mesmo bucket
    await _drain()

    assert len(sleeper.calls) == 1


async def test_concurrent_waits_in_one_bucket_serialize(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Sem o lock, as duas chamadas leem a mesma janela vazia, nenhuma
    dorme, e os dois identifies saem juntos — exatamente o que a janela
    existe para impedir.

    O `FakeSleeper` cede o turno, então quem entra depois do `await`
    enxerga a janela que a primeira espera acabou de criar.
    """
    throttler = _throttler(clock, sleeper, max_concurrency=1)

    await asyncio.gather(throttler.wait(0), throttler.wait(0))
    await _drain()

    assert len(sleeper.calls) == 1


def test_throttler_configuration_is_validated() -> None:
    with pytest.raises(ValueError, match="max_concurrency"):
        IdentifyThrottler(max_concurrency=0)
    with pytest.raises(ValueError, match="interval"):
        IdentifyThrottler(interval=0.0)
    with pytest.raises(ValueError, match="jitter"):
        IdentifyThrottler(jitter=-1.0)


def test_bucket_for_is_the_discord_formula() -> None:
    throttler = IdentifyThrottler(max_concurrency=16)
    assert throttler.bucket_for(0) == 0
    assert throttler.bucket_for(15) == 15
    assert throttler.bucket_for(16) == 0
    assert throttler.bucket_for(17) == 1


def test_default_properties_are_resolved_at_call_time() -> None:
    """Função, e não constante: o ``os`` só é conhecido em runtime, e um
    módulo que captura ``platform.system()`` no import fica com o valor
    errado se o processo migrar."""
    props = IdentifyProperties()
    assert props.os
    assert props.to_dict().keys() == {"os", "browser", "device"}
