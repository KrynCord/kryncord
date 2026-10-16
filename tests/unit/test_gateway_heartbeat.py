"""Testes de `kryncord.gateway.heartbeat` — o batimento e o zumbi.

Dois objetos, dois estilos de teste. `HeartbeatState` é puro: a pilha de
asserts dele não cria task nem dorme. `Heartbeat` agenda de verdade — mas
com um sleeper que anota em vez de dormir e um ``send`` que registra, sem
event loop se enrolando para sempre.

O fenômeno central é a **conexão zumbi**: heartbeat mandado, ``ACK`` nunca
chega. Do lado de lá a conexão está boa, do nosso não — e a única prova é
a ausência da resposta. Detectar isso tarde é mandar mensagem para o
vazio achando que foi entregue.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from kryncord.errors import LifecycleError
from kryncord.gateway.heartbeat import Heartbeat, HeartbeatState
from tests.conftest import FakeClock


class Recorder:
    """Registra os heartbeats enviados, e o que o `on_zombie` viu."""

    def __init__(self) -> None:
        self.sent: list[int | None] = []
        self.zombies = 0

    async def send(self, sequence: int | None) -> None:
        self.sent.append(sequence)

    async def on_zombie(self) -> None:
        self.zombies += 1


# --------------------------------------------------------------------------
# HeartbeatState — puro
# --------------------------------------------------------------------------


def test_state_starts_clean() -> None:
    state = HeartbeatState()
    assert state.awaiting_ack is False
    assert state.is_zombie is False
    assert state.latency_ms is None
    assert state.beats == 0
    assert state.acks == 0


def test_mark_sent_arms_the_pending_window() -> None:
    clock = FakeClock()
    state = HeartbeatState(clock=clock)

    instant = state.mark_sent()

    assert instant == clock.now
    assert state.awaiting_ack is True
    assert state.is_zombie is True
    assert state.beats == 1


def test_ack_measures_latency_and_clears_the_window() -> None:
    clock = FakeClock()
    state = HeartbeatState(clock=clock)

    state.mark_sent()
    clock.advance(0.037)
    latency = state.ack()

    assert latency == pytest.approx(37.0)
    assert state.latency_ms == pytest.approx(37.0)
    assert state.awaiting_ack is False
    assert state.is_zombie is False
    assert state.acks == 1


def test_ack_without_pending_returns_none() -> None:
    """ACK duplicado, ou atrasado que chegou depois de outro já limpar.

    Não é erro — é o lado melhor de uma rede.
    """
    state = HeartbeatState()
    assert state.ack() is None
    assert state.acks == 1  # contado mesmo assim, para diagnóstico


def test_extra_send_does_not_extend_the_deadline() -> None:
    """Um ``op 1`` do Discord manda heartbeat entre dois batimentos.

    Se cada envio re-armasse a flag, o prazo estenderia e o zumbi
    ficaria indetectável por mais um intervalo inteiro.
    """
    clock = FakeClock()
    state = HeartbeatState(clock=clock)

    state.mark_sent()
    clock.advance(0.5)
    state.mark_sent()  # o pedido do servidor
    clock.advance(0.5)

    assert state.pending_since == 1000.0  # o instante original, não o novo

    latency = state.ack()
    assert latency == pytest.approx(1000.0)
    assert state.beats == 2


def test_reset_clears_pending_but_keeps_counters() -> None:
    """Zumbi de uma sessão morta não pode nascer na sessão nova."""
    clock = FakeClock()
    state = HeartbeatState(clock=clock)

    state.mark_sent()
    state.reset()

    assert state.is_zombie is False
    assert state.last_sent_at is None
    # Contadores sobrevivem: são diagnóstico da conexão inteira.
    assert state.beats == 1


def test_snapshot_is_loggable() -> None:
    clock = FakeClock()
    state = HeartbeatState(clock=clock)
    state.mark_sent()
    clock.advance(0.01)
    state.ack()

    snapshot = state.snapshot()

    assert snapshot["beats"] == 1
    assert snapshot["acks"] == 1
    assert snapshot["awaiting_ack"] is False
    assert snapshot["latency_ms"] == pytest.approx(10.0)


# --------------------------------------------------------------------------
# Heartbeat — o agendador
# --------------------------------------------------------------------------


async def _settle(steps: int = 100) -> None:
    for _ in range(steps):
        await asyncio.sleep(0)


def _fake_sleeper() -> Callable[[float], Awaitable[None]]:
    """Espera que só cede o turno.

    Sem ceder, a task do batimento giraria sem nunca dar chance ao teste
    de pará-la — o teste não travaria por lentidão, travaria por nunca
    voltar.
    """

    async def _sleep(seconds: float) -> None:
        await asyncio.sleep(0)

    return _sleep


async def test_heartbeat_sends_on_the_interval() -> None:
    recorder = Recorder()
    heartbeat = Heartbeat(sleeper=_fake_sleeper(), random=lambda: 0.0)

    async def send_and_ack(sequence: int | None) -> None:
        recorder.sent.append(sequence)
        heartbeat.state.ack()

    heartbeat.start(1000.0, send=send_and_ack, sequence=lambda: 7)
    await _settle()
    await heartbeat.stop()

    # Sem `ACK` a segunda batida já seria zumbi — ver o teste vizinho.
    # O sleeper falso não dorme, então o `settle` produz muitas batidas:
    # o ponto é que elas **continuam**, e todas levam a sequence.
    assert len(recorder.sent) > 1
    assert set(recorder.sent) == {7}
    assert heartbeat.running is False


async def test_first_wait_is_jittered_over_one_interval() -> None:
    """Sem jitter, 100 shards iniciadas batem no mesmo milissegundo.

    O Discord vê um pico sincronizado que parece ataque.
    """
    recorder = Recorder()
    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)
        await asyncio.sleep(0)

    heartbeat = Heartbeat(sleeper=_sleep, random=lambda: 0.5)

    async def send_and_ack(sequence: int | None) -> None:
        recorder.sent.append(sequence)
        heartbeat.state.ack()

    heartbeat.start(1000.0, send=send_and_ack)
    await _settle()
    await heartbeat.stop()

    # O `start()` recebe milissegundos; a espera é em segundos —
    # 0.5 * 1000ms de espera inicial, depois o intervalo cheio.
    assert slept[0] == pytest.approx(0.5)
    assert slept[1] == pytest.approx(1.0)
    assert len(recorder.sent) >= 2


async def test_zombie_is_detected_before_the_next_beat() -> None:
    """Sem `ACK`, a conexão é declarada morta — e o `on_zombie` roda."""
    recorder = Recorder()
    heartbeat = Heartbeat(sleeper=_fake_sleeper(), random=lambda: 0.0)

    async def send_no_ack(sequence: int | None) -> None:
        recorder.sent.append(sequence)  # nunca responde

    heartbeat.start(100.0, send=send_no_ack, on_zombie=recorder.on_zombie)
    await _settle()
    await heartbeat.stop()

    # Mandou uma vez; na segunda checagem viu o pendente e parou.
    assert len(recorder.sent) == 1
    assert recorder.zombies == 1


async def test_ack_keeps_the_connection_alive() -> None:
    clock = FakeClock()
    recorder = Recorder()
    heartbeat = Heartbeat(
        state=HeartbeatState(clock=clock), sleeper=_fake_sleeper(), random=lambda: 0.0
    )

    async def send_and_ack(sequence: int | None) -> None:
        recorder.sent.append(sequence)
        heartbeat.state.ack()

    heartbeat.start(100.0, send=send_and_ack, on_zombie=recorder.on_zombie)
    await _settle()
    await heartbeat.stop()

    assert recorder.zombies == 0
    assert len(recorder.sent) > 1


async def test_beat_now_skips_the_zombie_check() -> None:
    """Um ``op 1`` veio pelo mesmo socket que estaríamos declarando morto.

    Se ele chegou, o socket não está morto. Recusar mandar seria fechar
    uma conexão saudável.
    """
    recorder = Recorder()
    heartbeat = Heartbeat(sleeper=_fake_sleeper(), random=lambda: 0.0)
    heartbeat.start(100.0, send=recorder.send, on_zombie=recorder.on_zombie)

    # Simula um batimento sem resposta: agora estamos "zumbis".
    heartbeat.state.mark_sent()
    await heartbeat.beat_now()

    assert recorder.sent == [None]
    assert recorder.zombies == 0

    await heartbeat.stop()


async def test_stop_is_idempotent() -> None:
    heartbeat = Heartbeat(sleeper=_fake_sleeper(), random=lambda: 0.0)
    heartbeat.start(100.0, send=Recorder().send)

    await heartbeat.stop()
    await heartbeat.stop()

    assert heartbeat.running is False


async def test_start_twice_is_a_lifecycle_error() -> None:
    """Dois batimentos na mesma conexão = alguém perdeu o `stop()`.

    A consequência seria o dobro de envio; um erro legível é melhor.
    """
    heartbeat = Heartbeat(sleeper=_fake_sleeper(), random=lambda: 0.0)
    heartbeat.start(100.0, send=Recorder().send)

    with pytest.raises(LifecycleError, match="já está rodando"):
        heartbeat.start(100.0, send=Recorder().send)

    await heartbeat.stop()


def test_start_rejects_non_positive_interval() -> None:
    heartbeat = Heartbeat()
    with pytest.raises(ValueError, match="positivo"):
        heartbeat.start(0.0, send=Recorder().send)
    with pytest.raises(ValueError, match="positivo"):
        heartbeat.start(-5.0, send=Recorder().send)


async def test_interval_is_in_seconds_not_ms() -> None:
    heartbeat = Heartbeat(sleeper=_fake_sleeper(), random=lambda: 0.0)
    heartbeat.start(41250.0, send=Recorder().send)

    assert heartbeat.interval == 41.25

    await heartbeat.stop()
    assert heartbeat.interval == 41.25  # preservado para diagnóstico


async def test_beat_now_before_start_raises() -> None:
    heartbeat = Heartbeat()
    with pytest.raises(LifecycleError, match="não iniciado"):
        await heartbeat.beat_now()
