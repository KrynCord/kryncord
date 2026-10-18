"""Fases do `GatewayClient`: abrir, apresentar, entregar, voltar.

Cada teste roda o `connect()` de verdade numa task e observa o que
saiu — só que o "Discord" é uma fila de frames e a espera é um
`sleeper` que anota em vez de dormir. Nenhum teste aqui abre um socket.
"""

from __future__ import annotations

import asyncio

import pytest

from kryncord.config import GatewayConfig
from kryncord.enums import GatewayOpcode
from kryncord.errors import FatalGatewayError, GatewayError, LifecycleError
from kryncord.gateway.client import GatewayClient, GatewayStatus
from kryncord.gateway.compression import CompressionMode
from kryncord.gateway.payloads import Payload
from kryncord.gateway.reconnect import ReconnectPolicy
from tests.conftest import FakeClock, FakeGatewayTransport, FakeSleeper

#: Corpo do `READY`, com o que `SessionInfo` exige.
READY_DATA = {
    "session_id": "sessao-0123456789abcdef",
    "resume_gateway_url": "wss://bogusb.discord.gg",
    "user": {"id": "1", "username": "prova"},
}

HELLO_INTERVAL_MS = 41250


def hello() -> Payload:
    return Payload(op=GatewayOpcode.HELLO, data={"heartbeat_interval": HELLO_INTERVAL_MS})


def ready(sequence: int = 1) -> Payload:
    return Payload(
        op=GatewayOpcode.DISPATCH, data=READY_DATA, sequence=sequence, event_name="READY"
    )


def resumed(sequence: int = 7) -> Payload:
    return Payload(op=GatewayOpcode.DISPATCH, data=None, sequence=sequence, event_name="RESUMED")


async def settle(steps: int = 200) -> None:
    """Roda o event loop até as tasks assedarem. Cede, mas não dorme.

    `asyncio.sleep(0)` é uma dívida de um ciclo de loop, não uma espera:
    um teste que fizesse `await asyncio.sleep(0.05)` para "esperar o
    bot conectar" estaria medindo a velocidade da máquina, não o
    comportamento da biblioteca.
    """
    for _ in range(steps):
        await asyncio.sleep(0)


def make_gateway(
    transport: FakeGatewayTransport,
    *,
    clock: FakeClock,
    sleeper: FakeSleeper,
    **kwargs: object,
) -> GatewayClient:
    kwargs.setdefault("random_source", lambda: 0.5)
    return GatewayClient(
        token="token-de-prova",
        intents=512,
        transport_factory=lambda: transport,
        clock=clock,
        sleeper=sleeper,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


async def run_until_ready(gateway: GatewayClient, *, steps: int = 400) -> asyncio.Task[None]:
    task = asyncio.create_task(gateway.connect())
    for _ in range(steps):
        if gateway.ready:
            return task
        if task.done():
            await task  # levanta a exceção real, não um AssertionError vago
            raise AssertionError("`connect()` terminou sem chegar ao READY")
        await asyncio.sleep(0)
    await gateway.close()
    with pytest.raises(BaseException):  # noqa: B017 - só para não vazar a task
        await task
    raise AssertionError(f"Não ficou READY em {steps} ciclos (status={gateway.status})")


# ---------------------------------------------------------------------------
# Apresentação
# ---------------------------------------------------------------------------


async def test_connect_identifies_and_reaches_ready(clock: FakeClock, sleeper: FakeSleeper) -> None:
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = await run_until_ready(gateway)

    # O Identify é sempre o primeiro frame enviado.
    assert transport.opcodes[0] == GatewayOpcode.IDENTIFY
    assert transport.identify["intents"] == 512
    assert transport.identify["token"] == "token-de-prova"
    assert gateway.status is GatewayStatus.READY
    assert gateway.session_id == READY_DATA["session_id"]

    await gateway.close()
    await task


async def test_heartbeat_starts_only_after_identify(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Nunca bater o coração antes de se apresentar.

    Um `HEARTBEAT` antes do `IDENTIFY` é `4003 Not Authenticated` — o
    discord.js aceita a corrida porque inicia o timer no `HELLO`; aqui o
    timer só começa depois do envio, e a ordem fica garantida.
    """
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(
        transport,
        clock=clock,
        sleeper=sleeper,
        # Jitter em zero: o primeiro batimento sai sem esperar, o que
        # torna qualquer inversão de ordem visível na hora.
        random_source=lambda: 0.0,
    )
    task = await run_until_ready(gateway)
    await settle()

    assert transport.opcodes[0] == GatewayOpcode.IDENTIFY
    assert GatewayOpcode.HEARTBEAT in transport.opcodes
    assert transport.opcodes.index(GatewayOpcode.HEARTBEAT) > 0

    # O payload carrega a sequence corrente, mesmo sendo a primeira.
    beat = next(p for p in transport.sent if p["op"] == GatewayOpcode.HEARTBEAT)
    assert beat["d"] == 1

    await gateway.close()
    await task


async def test_connection_url_carries_version_and_encoding(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = await run_until_ready(gateway)

    assert transport.connected_urls == ["wss://gateway.discord.gg/?v=10&encoding=json"]

    await gateway.close()
    await task


async def test_no_resume_when_there_is_no_session(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Primeira conexão: `IDENTIFY`, nunca `RESUME`."""
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = await run_until_ready(gateway)

    assert transport.opcodes.count(GatewayOpcode.RESUME) == 0

    await gateway.close()
    await task


async def test_ready_without_session_never_counts_as_ready(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Um `READY` sem `session_id` derruba a tentativa, não a renomeia.

    `max_reconnect_attempts=0` desliga a reconexão de propósito: o que
    interessa aqui é que a **primeira** tentativa recusou o `READY`,
    sem a segunda tentativa mascarar o resultado.
    """
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(
        Payload(
            op=GatewayOpcode.DISPATCH,
            data={"resume_gateway_url": "wss://x"},
            sequence=1,
            event_name="READY",
        )
    )

    gateway = make_gateway(
        transport,
        clock=clock,
        sleeper=sleeper,
        config=GatewayConfig(max_reconnect_attempts=0),
    )
    task = asyncio.create_task(gateway.connect())

    # O `wait_for` não atrasa quem passa: devolve no instante em que a
    # task termina. Existe para que script incompleto vire falha em
    # segundos, não em build pendurada.
    with pytest.raises(GatewayError) as excinfo:
        await asyncio.wait_for(task, timeout=2.0)

    assert "session_id" in str(excinfo.value)
    assert gateway.status is GatewayStatus.CLOSED
    assert not gateway.ready


# ---------------------------------------------------------------------------
# Entrega de eventos
# ---------------------------------------------------------------------------


async def test_dispatch_events_reach_the_handler(clock: FakeClock, sleeper: FakeSleeper) -> None:
    seen: list[tuple[str, object]] = []

    async def on_event(name: str, data: object) -> None:
        seen.append((name, data))

    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper, on_event=on_event)
    task = await run_until_ready(gateway)

    transport.feed_payload(
        Payload(
            op=GatewayOpcode.DISPATCH,
            data={"content": "oi"},
            sequence=2,
            event_name="MESSAGE_CREATE",
        )
    )
    await settle()

    assert ("MESSAGE_CREATE", {"content": "oi"}) in seen
    # A sequence é rastreada mesmo para eventos que ninguém escuta.
    assert gateway.sequence == 2

    await gateway.close()
    await task


async def test_event_handler_error_does_not_kill_the_loop(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    async def on_event(name: str, data: object) -> None:
        if name == "MESSAGE_CREATE":
            raise RuntimeError("handler quebrado")

    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper, on_event=on_event)
    task = await run_until_ready(gateway)

    transport.feed_payload(
        Payload(
            op=GatewayOpcode.DISPATCH,
            data={"content": "oi"},
            sequence=2,
            event_name="MESSAGE_CREATE",
        )
    )
    transport.feed_payload(
        Payload(
            op=GatewayOpcode.DISPATCH,
            data={"content": "depois"},
            sequence=3,
            event_name="MESSAGE_CREATE",
        )
    )
    await settle()

    assert not task.done(), "um handler com erro derrubou o loop do Gateway"
    assert gateway.sequence == 3

    await gateway.close()
    await task


async def test_sequence_is_stored_on_every_dispatch(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """O `RESUME` precisa da sequence corrente, não da do `READY`.

    Guardar só a do `READY` faria a retomada reenviar tudo desde o
    início — ou, pior, falhar com `4007 Invalid Seq`.
    """
    from kryncord.gateway.session import InMemorySessionStore

    store = InMemorySessionStore()
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready(sequence=1))

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper, session_store=store)
    task = await run_until_ready(gateway)

    for sequence in (2, 3, 4):
        transport.feed_payload(
            Payload(
                op=GatewayOpcode.DISPATCH,
                data={},
                sequence=sequence,
                event_name="TYPING_START",
            )
        )
    await settle()

    stored = await store.retrieve(0)
    assert stored is not None
    assert stored.sequence == 4
    assert gateway.sequence == 4

    await gateway.close()
    await task


# ---------------------------------------------------------------------------
# Reconexão
# ---------------------------------------------------------------------------


async def test_normal_close_identifies_again(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Código 1000 encerra a sessão — `IDENTIFY`, não `RESUME`."""
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())
    transport.drop(code=1000, reason="sessão encerrada")
    # Da reconexão em diante, é outro socket:
    transport.feed_payload_next(hello())
    transport.feed_payload_next(ready(sequence=9))

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = asyncio.create_task(gateway.connect())
    await settle()

    assert transport.opcodes.count(GatewayOpcode.IDENTIFY) == 2
    assert transport.opcodes.count(GatewayOpcode.RESUME) == 0

    await gateway.close()
    await task


async def test_drops_to_resume_after_ready_when_session_survives(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """4009 é transitório: com sessão guardada, volta com `RESUME`."""
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())
    transport.drop(code=4009, reason="sessão expirou")
    transport.feed_payload_next(hello())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = asyncio.create_task(gateway.connect())
    await settle()

    assert transport.opcodes.count(GatewayOpcode.RESUME) == 1
    resume = transport.resume
    assert resume["session_id"] == READY_DATA["session_id"]
    assert resume["seq"] == 1

    # A URL de retomada é a que veio no `READY`, não a base.
    assert "bogusb.discord.gg" in transport.connected_urls[-1]

    await gateway.close()
    await task


async def test_resume_is_downgraded_to_identify_without_session(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Código retomável **sem** sessão não é retomada, é recomeço.

    Tentar `RESUME` aqui seria pagar um round-trip para levar
    `invalid_session` de volta — o `IDENTIFY` já resolve de primeira.
    """
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())  # nunca chega no `READY`
    transport.drop(code=4009, reason="sessão expirou")
    transport.feed_payload_next(hello())
    transport.feed_payload_next(ready())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = asyncio.create_task(gateway.connect())
    await settle()

    assert transport.opcodes.count(GatewayOpcode.RESUME) == 0
    assert transport.opcodes.count(GatewayOpcode.IDENTIFY) == 2

    await gateway.close()
    await task


async def test_fatal_close_code_raises_and_stops(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """4014 (intents não permitidos) não se recupera reconectando."""
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.drop(code=4014, reason="intents não permitidos")

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = asyncio.create_task(gateway.connect())

    with pytest.raises(FatalGatewayError) as excinfo:
        await asyncio.wait_for(task, timeout=2.0)
    assert excinfo.value.code == 4014
    assert gateway.status is GatewayStatus.CLOSED
    # Nem uma segunda tentativa: o teto aqui é zero.
    assert len(transport.connected_urls) == 1


async def test_authentication_failed_is_fatal(clock: FakeClock, sleeper: FakeSleeper) -> None:
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.drop(code=4004, reason="token inválido")

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = asyncio.create_task(gateway.connect())

    with pytest.raises(FatalGatewayError) as excinfo:
        await asyncio.wait_for(task, timeout=2.0)
    assert excinfo.value.code == 4004


async def test_gives_up_after_max_reconnect_attempts(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Teto de tentativas: depois disso, `connect()` desiste em voz alta.

    Chegar ao `READY` na primeira tentativa zera a contagem, então são
    precisas **duas** quedas seguidas para estourar `max_attempts=2` —
    o que é exatamente o contrato de "falhas consecutivas".
    """
    transport = FakeGatewayTransport(auto_ack=False)
    transport.feed_payload(hello())
    transport.feed_payload(ready())
    transport.drop(code=1000, reason="queda 1")
    # Tentativa 2: sobe e cai de novo, sem chegar ao `READY`...
    transport.feed_payload_next(hello())
    transport.drop_next(code=1000, reason="queda 2")
    # Tentativa 3: a última, e também cai.
    transport.feed_payload_next(hello())
    transport.drop_next(code=1000, reason="queda 3")

    gateway = make_gateway(
        transport,
        clock=clock,
        sleeper=sleeper,
        config=GatewayConfig(max_reconnect_attempts=2),
        random_source=lambda: 0.0,  # jitter em zero: backoff previsível
    )
    task = asyncio.create_task(gateway.connect())

    with pytest.raises(GatewayError) as excinfo:
        await asyncio.wait_for(task, timeout=2.0)

    assert "reconexão feitas: 2" in str(excinfo.value)
    assert gateway.status is GatewayStatus.CLOSED
    # Abriu a inicial + 2 tentativas; a 3ª nunca chegou a abrir.
    assert len(transport.connected_urls) == 3
    # Backoff registrado, mesmo sem ter dormido de verdade.
    # Com jitter 0.5 e random 0.0: equal jitter dá metade do exponencial.
    # As esperas se **misturam**: backoff, janela de identify (5s),
    # backoff, janela de novo — porque toda reconexão paga os dois
    # teto. O que importa aqui é a ordem dos backoffs.
    backoffs = [call for call in sleeper.calls if call < 1.0]
    assert backoffs == [0.25, 0.5]


async def test_reaching_ready_resets_the_failure_counter(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """As falhas são consecutivas, não totais.

    Um bot que viveu seis horas não pode começar a segunda queda já com
    o orçamento gasto — senão `max_reconnect_attempts` vira um limite
    de vida útil, não de instabilidade.

    Aqui o teto é 1: **uma** queda seguida já derrubaria. Chegar ao
    `READY` entre elas zera a contagem, e o bot sobrevive a 3 ciclos.
    """
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())
    transport.drop(code=1000, reason="queda 1")
    transport.feed_payload_next(hello())
    transport.feed_payload_next(ready(sequence=2))
    transport.drop_next(code=1000, reason="queda 2")
    transport.feed_payload_next(hello())
    transport.feed_payload_next(ready(sequence=3))
    transport.drop_next(code=1000, reason="queda 3")

    gateway = make_gateway(
        transport,
        clock=clock,
        sleeper=sleeper,
        config=GatewayConfig(max_reconnect_attempts=1),
        random_source=lambda: 0.0,
    )
    task = asyncio.create_task(gateway.connect())
    await settle()

    assert transport.opcodes.count(GatewayOpcode.IDENTIFY) == 3
    assert not task.done(), "desistiu no meio, apesar de ter chegado ao READY"

    await gateway.close()
    await task


async def test_zombie_connection_closes_with_resuming_code(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Heartbeat sem `ACK` → fecha com 4200 → retoma sessão.

    `auto_ack=False` é o que permite ver o fenômeno: sem o `ACK` voltando,
    a próxima checagem encontra o batimento pendente e a conexão é
    declarada morta — mesmo estando tecnicamente aberta.
    """
    transport = FakeGatewayTransport(auto_ack=False)
    transport.feed_payload(hello())
    transport.feed_payload(ready())
    transport.feed_payload_next(hello())

    gateway = make_gateway(
        transport,
        clock=clock,
        sleeper=sleeper,
        random_source=lambda: 0.0,  # primeiro batimento sem espera
    )
    task = asyncio.create_task(gateway.connect())
    await settle()

    assert transport.closes[:1] == [(4200, "Zombie connection")]
    assert transport.opcodes.count(GatewayOpcode.RESUME) == 1

    await gateway.close()
    await task


async def test_invalid_session_identifies_again(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """`op 9` com `d: false` — a sessão morreu, recomeça do zero."""
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())
    transport.feed_payload(Payload(op=GatewayOpcode.INVALID_SESSION, data=False))
    transport.feed_payload_next(hello())
    transport.feed_payload_next(ready(sequence=5))

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = asyncio.create_task(gateway.connect())
    await settle()

    assert transport.opcodes.count(GatewayOpcode.IDENTIFY) == 2
    assert transport.opcodes.count(GatewayOpcode.RESUME) == 0

    await gateway.close()
    await task


async def test_invalid_session_resumable_nao_dorme_antes_de_retomar(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """`op 9` com `d: true` → retoma sem espera extra de 1 a 5 segundos.

    A espera aleatória que existia aqui empilhava com o backoff da
    reconexão — o `@discordjs/ws` a removeu pelo mesmo motivo: o
    anti-thrash do backoff e o teto de 5s do throttler de identify já
    cobrem a recuperação sozinhos.
    """
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())
    transport.feed_payload(Payload(op=GatewayOpcode.INVALID_SESSION, data=True))
    transport.feed_payload_next(hello())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = asyncio.create_task(gateway.connect())
    await settle()

    assert transport.opcodes.count(GatewayOpcode.RESUME) == 1
    # Nenhuma espera na faixa de 1–5s: o backoff da política (~0,4s na
    # primeira tentativa) é o único delay do caminho.
    assert not any(1.0 <= call <= 5.0 for call in sleeper.calls)

    await gateway.close()
    await task


# ---------------------------------------------------------------------------
# Prazo do READY
# ---------------------------------------------------------------------------


async def test_ready_nao_chega_em_tempo_reconecta(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Sem `READY`, o prazo do config derruba a tentativa e tenta de novo.

    `ready_timeout` existia no config e nada o aplicava: um Discord que
    aceitasse o socket e ficasse calado deixaria o bot "ligado" para
    sempre — heartbeat batendo, ACK chegando, nada zumbi, e a sessão
    nunca existe. Nesse estado, nenhum log parece errado.
    """
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload_next(hello())

    gateway = make_gateway(
        transport,
        clock=clock,
        sleeper=sleeper,
        config=GatewayConfig(max_reconnect_attempts=1, ready_timeout=0.05),
    )
    task = asyncio.create_task(gateway.connect())

    with pytest.raises(GatewayError) as excinfo:
        await asyncio.wait_for(task, timeout=2.0)

    assert "READY" in str(excinfo.value)
    # Duas tentativas: a primeira expirou no prazo, a segunda esgotou o
    # teto de reconexão com o mesmo motivo.
    assert transport.opcodes.count(GatewayOpcode.IDENTIFY) == 2


async def test_resumed_tambem_tem_prazo(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Quem retoma também tem prazo: `RESUMED` que não chega é o mesmo
    hang do `READY` que não chega — e o custo de tentar de novo é
    idêntico. É o `readyTimeout` do discord.js estendido ao resume."""
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())
    transport.drop(code=4000, reason="queda transitória")
    transport.feed_payload_next(hello())
    # A segunda conexão manda RESUME... e o `RESUMED` nunca vem.

    gateway = make_gateway(
        transport,
        clock=clock,
        sleeper=sleeper,
        config=GatewayConfig(max_reconnect_attempts=1, ready_timeout=0.05),
    )
    task = asyncio.create_task(gateway.connect())

    with pytest.raises(GatewayError) as excinfo:
        await asyncio.wait_for(task, timeout=2.0)

    assert "READY" in str(excinfo.value)
    assert transport.opcodes.count(GatewayOpcode.RESUME) == 1


async def test_ready_rapido_nao_paga_prazo_nenhum(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Prazo curto no config e `READY` instantâneo: nada de timeout.

    É a regressão do caminho feliz — o prazo só corta silêncio, nunca
    quem responde a tempo.
    """
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(
        transport, clock=clock, sleeper=sleeper, config=GatewayConfig(ready_timeout=0.05)
    )
    task = await run_until_ready(gateway)

    assert gateway.ready

    await gateway.close()
    await task


async def test_identify_e_heartbeat_nao_contam_no_budget(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Identify e heartbeat são ops importantes: o budget de 115 frames
    é dos eventos, como no discord.js (`ImportantGatewayOpcodes`).
    Contar batimento seria pagar ~2 frames de janela por minuto à toa."""
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = await run_until_ready(gateway)
    await settle()  # deixa ao menos um heartbeat passar pelo envio

    assert gateway._heartbeat.state.beats >= 1
    assert gateway._send_limit.remaining == gateway._send_limit.limit - 1

    await gateway.close()
    await task


async def test_reconnect_opcode_asks_for_resume(clock: FakeClock, sleeper: FakeSleeper) -> None:
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())
    transport.feed_payload(Payload(op=GatewayOpcode.RECONNECT))
    transport.feed_payload_next(hello())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = asyncio.create_task(gateway.connect())
    await settle()

    assert transport.opcodes.count(GatewayOpcode.RESUME) == 1

    await gateway.close()
    await task


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


async def test_close_stops_connect_promptly(clock: FakeClock, sleeper: FakeSleeper) -> None:
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = asyncio.create_task(gateway.connect())
    await settle()
    assert gateway.ready

    await gateway.close()
    await asyncio.wait_for(task, timeout=1.0)

    assert gateway.status is GatewayStatus.CLOSED
    assert not gateway.ready


async def test_close_interrupts_backoff_wait(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """`close()` durante o backoff não espera a espera terminar.

    Um bot em backoff de 60s que leva 60s para desligar é morto com
    SIGKILL pelo orquestrador — e o `finally` de `connect()` nem roda.
    """
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.drop(code=1000, reason="queda")

    gateway = make_gateway(
        transport,
        clock=clock,
        sleeper=sleeper,
        # Espera enorme e infinitas tentativas: se `close()` não
        # interromper a espera, este teste nunca termina.
        policy=ReconnectPolicy(max_attempts=None, base_delay=600.0, max_delay=600.0, jitter=0.0),
    )
    task = asyncio.create_task(gateway.connect())
    await settle()

    # Atenção: o sleeper já foi chamado com 600 — é isso que prova que
    # estávamos no meio do backoff quando o `close()` chegou.
    assert 600.0 in sleeper.calls

    await gateway.close()
    # Um timeout curto AQUI é o teste. Se a espera não fosse
    # interrompível, `wait_for` estouraria.
    await asyncio.wait_for(task, timeout=1.0)
    assert gateway.status is GatewayStatus.CLOSED


async def test_connect_twice_is_a_lifecycle_error(clock: FakeClock, sleeper: FakeSleeper) -> None:
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = asyncio.create_task(gateway.connect())
    await settle()

    with pytest.raises(LifecycleError):
        await gateway.connect()

    await gateway.close()
    await task


async def test_close_without_connect_is_idempotent(clock: FakeClock, sleeper: FakeSleeper) -> None:
    gateway = make_gateway(FakeGatewayTransport(), clock=clock, sleeper=sleeper)
    await gateway.close()
    await gateway.close()
    assert gateway.status is GatewayStatus.CLOSED


async def test_connection_error_before_hello_is_retried(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Erro de rede sem código de fechamento → reconecta.

    Sem `session_id`, a retomada não é opção — o `IDENTIFY` é o caminho.
    """
    transport = FakeGatewayTransport()
    transport.connect_error = OSError("sem rota até o host")
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = asyncio.create_task(gateway.connect())
    await settle()

    assert transport.opcodes.count(GatewayOpcode.IDENTIFY) == 1

    await gateway.close()
    await task


async def test_compression_query_param_is_sent_when_requested(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(
        transport,
        clock=clock,
        sleeper=sleeper,
        compression=CompressionMode.ZLIB_STREAM,
    )
    task = await run_until_ready(gateway)

    assert "compress=zlib-stream" in transport.connected_urls[0]

    await gateway.close()
    await task


# --------------------------------------------------------------------------
# Latência
# --------------------------------------------------------------------------


async def test_latency_none_antes_do_primeiro_ack() -> None:
    """`latency` é o round-trip do heartbeat em ms (``op 1`` →
    ``ACK``) — o mesmo número que o ``client.latency`` do discord.py
    (segundos) e o ``client.ws.ping`` do discord.js (ms) mostram.

    `None` antes da primeira medição: zero aqui diria "perfeição"
    sobre algo que nunca foi medido. Mandado mas não respondido
    também é `None` — a resposta é que mede, não o envio."""
    clock = FakeClock()
    gateway = make_gateway(FakeGatewayTransport(), clock=clock, sleeper=FakeSleeper(clock))

    assert gateway.latency is None

    gateway._heartbeat.state.mark_sent()
    assert gateway.latency is None

    gateway._heartbeat.state.ack()
    assert isinstance(gateway.latency, float)
    assert gateway.latency >= 0


async def test_latency_apos_o_ready_e_float(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """O caminho real: o transporte com `auto_ack` imita o Discord, o
    heartbeat bate e o ACK chega — a latência fica legível sem nada
    de extra do chamador."""
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())

    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = await run_until_ready(gateway)
    await settle()

    assert isinstance(gateway.latency, float)

    await gateway.close()
    await task
