"""Testes de `kryncord.gateway.connection` — o teto de envio do socket.

`WebSocketConnection` é coberto indiretamente: ela só embrulha o
`websockets`, e testá-la exigiria um socket de verdade — que é justamente
o que este projeto proíbe. O que mora aqui é `GatewaySendRateLimit`, que
fica **fora** do transporte de propósito: assim o teste roda sem rede.

A conta é a do discord.js, e ela é conservadora de propósito: o limite
documentado do Discord é 120, e nós paramos no 114º. Errar para o lado
da espera custa 1,5s; errar para o lado do envio custa a conexão — que
cai sem aviso nenhum.
"""

from __future__ import annotations

import asyncio

import pytest

from kryncord.gateway.connection import SEND_LIMIT, SEND_WINDOW, GatewaySendRateLimit
from tests.conftest import FakeClock, FakeSleeper


def _limit(clock: FakeClock, sleeper: FakeSleeper, **kwargs: object) -> GatewaySendRateLimit:
    kwargs.setdefault("random", lambda: 0.0)
    return GatewaySendRateLimit(clock=clock, sleeper=sleeper, **kwargs)  # type: ignore[arg-type]


async def test_sends_within_the_window_without_sleeping(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    limit = _limit(clock, sleeper)

    for _ in range(SEND_LIMIT - 1):
        await limit.acquire()

    assert sleeper.calls == []
    assert limit.remaining == 0


async def test_the_last_slot_waits_for_the_window_to_turn(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """O sentinela é ``sent + 1 >= limit``: o 115º envio é o que espera.

    É folga, não exatidão — chegar ao teto do Discord custa a conexão.
    """
    limit = _limit(clock, sleeper)

    for _ in range(SEND_LIMIT - 1):
        await limit.acquire()
    await limit.acquire()

    # Janela inteira mais jitter (zerado no teste).
    assert sleeper.calls == [pytest.approx(SEND_WINDOW)]


async def test_waiting_recharges_the_window(clock: FakeClock, sleeper: FakeSleeper) -> None:
    limit = _limit(clock, sleeper)

    for _ in range(SEND_LIMIT):
        await limit.acquire()

    # A espera virou a janela: só o frame que esperou já está no banco
    # novo, e o resto está livre de novo.
    assert limit.remaining == SEND_LIMIT - 2
    for _ in range(SEND_LIMIT - 2):
        await limit.acquire()
    assert sleeper.calls == [pytest.approx(SEND_WINDOW)]


async def test_a_short_wait_is_retried_instead_of_bursting(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """O ``while`` (e não um ``if``) existe: se a espera não bastar —
    relógio atrasando, jitter curto — espera de novo em vez de estourar.

    Aqui o relógio anda **20s fixos**, independente do que foi pedido.
    Um `if` mandaria o frame na hora, estourando o teto; o laço espera
    de novo e só sai com a janela inteira virada.
    """
    limit = _limit(clock, sleeper, jitter=0.0)
    sleeps = 0
    start = clock.now

    async def _short_sleep(seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        clock.advance(20.0)
        await asyncio.sleep(0)

    limit.sleeper = _short_sleep  # type: ignore[assignment]

    for _ in range(SEND_LIMIT - 1):
        await limit.acquire()

    await asyncio.wait_for(limit.acquire(), timeout=1.0)

    # Três esperas de 20s fecham os 60s da janela.
    assert sleeps == 3
    assert clock.now - start == pytest.approx(SEND_WINDOW)


async def test_jitter_is_what_the_random_source_gives(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    limit = GatewaySendRateLimit(clock=clock, sleeper=sleeper, random=lambda: 1.0, jitter=1.5)

    for _ in range(SEND_LIMIT):
        await limit.acquire()

    assert sleeper.calls == [pytest.approx(SEND_WINDOW + 1.5)]


async def test_remaining_reports_the_current_window_only(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    limit = _limit(clock, sleeper)
    assert limit.remaining == SEND_LIMIT - 1

    await limit.acquire()
    clock.advance(1.0)
    assert limit.remaining == SEND_LIMIT - 2

    # Janela vencida: o teto volta inteiro, sem ter enviado nada.
    clock.advance(SEND_WINDOW)
    assert limit.remaining == SEND_LIMIT - 1


def test_configuration_is_validated(clock: FakeClock, sleeper: FakeSleeper) -> None:
    with pytest.raises(ValueError, match="limit"):
        GatewaySendRateLimit(limit=0, clock=clock, sleeper=sleeper)
    with pytest.raises(ValueError, match="window"):
        GatewaySendRateLimit(window=0.0, clock=clock, sleeper=sleeper)
    with pytest.raises(ValueError, match="jitter"):
        GatewaySendRateLimit(jitter=-1.0, clock=clock, sleeper=sleeper)


def test_the_limit_has_margin_under_the_documented_one() -> None:
    """O Discord documenta 120; paramos antes. Folga é barata, close
    code 4008 no meio de um comando do usuário é caro."""
    assert SEND_LIMIT < 120
    assert SEND_WINDOW == 60.0


async def test_frames_importantes_nao_contam_no_budget(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Ops importantes (heartbeat/identify/resume) não gastam budget.

    É o `ImportantGatewayOpcodes` do discord.js: o teto de 115 frames
    é dos eventos de verdade. Contar batimento seria pagar ~2 frames de
    janela por minuto à toa.
    """
    limit = _limit(clock, sleeper)

    for _ in range(200):
        await limit.acquire(important=True)

    assert limit.remaining == SEND_LIMIT - 1

    for _ in range(SEND_LIMIT - 1):
        await limit.acquire()

    assert limit.remaining == 0


async def test_reset_por_conexao_zera_a_janela(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """O teto é por conexão: socket novo tem budget novo.

    É o `onopen` do discord.js, que zera `{sent, resetAt}` em todo
    (re)connect. Segurar o contador da conexão anterior seria pagar
    duas vezes por frames que nem foram na conexão nova.
    """
    limit = _limit(clock, sleeper)
    for _ in range(SEND_LIMIT - 1):
        await limit.acquire()
    assert limit.remaining == 0

    limit.reset()

    assert limit.remaining == SEND_LIMIT - 1
    # E o teto segue valendo na conexão nova: o 115º ainda espera.
    for _ in range(SEND_LIMIT - 1):
        await limit.acquire()
    assert limit.remaining == 0
