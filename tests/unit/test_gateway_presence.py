"""Presence em runtime (op 3): forma, teto e recusa fora de sessão.

Mesmo truque do resto da suíte do gateway: o socket é o
`FakeGatewayTransport`, o tempo é o `FakeSleeper` (que anota e avança o
relógio em vez de dormir), e nenhum teste abre rede.
"""

from __future__ import annotations

import pytest

from kryncord.enums import GatewayOpcode
from kryncord.errors import LifecycleError
from kryncord.gateway.presence import (
    PRESENCE_JITTER,
    PresenceRateLimit,
    build_presence_update,
)
from tests.conftest import FakeClock, FakeGatewayTransport, FakeSleeper
from tests.unit.test_gateway_client import hello, make_gateway, ready, run_until_ready


def _limit(clock: FakeClock, sleeper: FakeSleeper, **kwargs: object) -> PresenceRateLimit:
    return PresenceRateLimit(
        clock=clock,
        sleeper=sleeper,  # type: ignore[arg-type]
        random=lambda: 0.5,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# build_presence_update
# ---------------------------------------------------------------------------


def test_monta_op3_com_o_shape_do_discord() -> None:
    payload = build_presence_update(
        since=1234, afk=True, status="dnd", activities=[{"name": "KrynCord"}]
    )

    assert payload.op == GatewayOpcode.PRESENCE_UPDATE
    assert payload.data == {
        "since": 1234,
        "activities": [{"name": "KrynCord"}],
        "status": "dnd",
        "afk": True,
    }


def test_defaults_sao_os_do_discord() -> None:
    """`since: None`, `afk: False`, `status: "online"`, sem atividades."""
    payload = build_presence_update()
    assert payload.data == {
        "since": None,
        "activities": [],
        "status": "online",
        "afk": False,
    }


def test_status_invalido_rejeitado_listando_opcoes() -> None:
    """`ValueError` listando as opções — o frame errado ali vira close
    code, e recusar aqui custa uma exceção, não uma reconexão."""
    with pytest.raises(ValueError, match=r"online.*dnd.*idle.*invisible.*offline"):
        build_presence_update(status="foo")


def test_since_invalido_rejeitado() -> None:
    with pytest.raises(ValueError, match="since"):
        build_presence_update(since="1234")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Teto 5/20s
# ---------------------------------------------------------------------------


async def test_quinta_chamada_passa_sexta_espera(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """O Discord documenta 5 updates por 20s: a quinta é livre, a sexta
    dorme até a janela virar — sem drop silencioso, regra §13."""
    limit = _limit(clock, sleeper)

    for _ in range(5):
        await limit.acquire()
    assert sleeper.calls == []

    await limit.acquire()

    assert len(sleeper.calls) == 1
    assert sleeper.calls[0] == pytest.approx(
        # Espera até a janela virar (20s a menos o que já passou = nada,
        # acabou de abrir) + jitter sorteado (0.5 * 0.5).
        20.0 - 0.0 + 0.5 * PRESENCE_JITTER
    )


async def test_janela_virada_zera_o_teto(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Passou a janela, o teto recomeça do zero.

    A sexta chamada não só esperou como gastou o primeiro slot da
    janela nova — então cabem mais quatro livres, e nenhuma espera
    nova aparece.
    """
    limit = _limit(clock, sleeper)
    for _ in range(5):
        await limit.acquire()
    await limit.acquire()  # a sexta dorme e o FakeSleeper avança o relógio

    for _ in range(4):
        await limit.acquire()

    # Uma única espera em toda a história: só a sexta da primeira janela.
    assert len(sleeper.calls) == 1


# ---------------------------------------------------------------------------
# Fio inteiro (GatewayClient)
# ---------------------------------------------------------------------------


async def test_envio_passa_pelo_gateway(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Sessão pronta, `update_presence` manda o op 3 com os kwargs."""
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())
    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = await run_until_ready(gateway)

    await gateway.update_presence(status="idle", activities=[{"name": "prova"}])

    enviado = next(f for f in transport.sent if f["op"] == GatewayOpcode.PRESENCE_UPDATE)
    assert enviado["d"]["status"] == "idle"
    assert enviado["d"]["activities"] == [{"name": "prova"}]

    await gateway.close()
    await task


async def test_presenca_fora_de_ready_erro(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Fora de sessão a recusa é na cara — não enfileiro oculto."""
    transport = FakeGatewayTransport()
    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)

    with pytest.raises(LifecycleError, match="READY"):
        await gateway.update_presence()
