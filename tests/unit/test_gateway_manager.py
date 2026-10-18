"""Multi-shard manager: topologia, teto de identifies e falha fatal.

O "Discord" continua sendo o `FakeGatewayTransport` — um por shard,
entregue pela fárbica na ordem de conexão. O tempo continua sendo o
`FakeSleeper`. A novidade aqui é o conjunto: N conexões, um throttler só,
e a pergunta que só existe acima de uma shard — "e se uma morrer?".

Nenhum teste abre rede, e nenhum teste dorme: o pior caso de espera
(identify sequencial no mesmo bucket) é o `FakeSleeper` anotando e
adiando o relógio falso, como no resto da suíte.
"""

from __future__ import annotations

import asyncio

import pytest

from kryncord.enums import GatewayOpcode
from kryncord.errors import FatalGatewayError, GatewayError, LifecycleError
from kryncord.gateway.client import GatewayStatus
from kryncord.gateway.manager import GatewayManager
from kryncord.gateway.session import InMemorySessionStore, SessionInfo
from kryncord.models import GatewayBotInfo, SessionStartLimit
from tests.conftest import FakeClock, FakeGatewayTransport, FakeSleeper
from tests.unit.test_gateway_client import hello, ready, resumed, settle


def gateway_info(
    shards: int,
    *,
    remaining: int = 1000,
    max_concurrency: int = 1,
) -> GatewayBotInfo:
    """Um `/gateway/bot` de mentira, com o limite contando para a conta."""
    return GatewayBotInfo(
        url="wss://gateway.discord.gg",
        shards=shards,
        session_start_limit=SessionStartLimit(
            total=1000,
            remaining=remaining,
            reset_after=3600.0,
            max_concurrency=max_concurrency,
        ),
    )


def com_hello_e_ready(n: int) -> list[FakeGatewayTransport]:
    """`n` sockets simulados já com `HELLO` e `READY` enfileirados."""
    transports = []
    for _ in range(n):
        transport = FakeGatewayTransport()
        transport.feed_payload(hello())
        transport.feed_payload(ready())
        transports.append(transport)
    return transports


def make_manager(
    transports: list[FakeGatewayTransport],
    *,
    clock: FakeClock,
    sleeper: FakeSleeper,
    **kwargs: object,
) -> GatewayManager:
    """Manager com os transports entregues em ordem: shard 0, 1, ...

    A fábrica é compartilhada entre as shards (é o desenho), então a
    ordem de entrega é a ordem de conexão — determinística, porque as
    tasks das shards são criadas em ordem e o loop roda em FIFO.
    """
    fila = list(transports)

    def factory() -> FakeGatewayTransport:
        return fila.pop(0)

    return GatewayManager(
        token="token-de-prova",
        intents=512,
        transport_factory=factory,
        clock=clock,
        sleeper=sleeper,  # type: ignore[arg-type]
        random_source=lambda: 0.5,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Antes de conectar: validação da topologia e do teto
# ---------------------------------------------------------------------------


async def test_session_start_limit_insuficiente_erro(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """`remaining` menor que as shards: recusa na cara, com o reset na
    mensagem — "espera X segundos" é o que resolve, não "limite
    estourado". E a recusa vem **antes** de gastar um identify."""
    transports = com_hello_e_ready(2)
    manager = make_manager(
        transports,
        clock=clock,
        sleeper=sleeper,
        gateway_information=gateway_info(2, remaining=1),
    )

    with pytest.raises(GatewayError, match="3600"):
        await manager.connect()

    assert all(transport.sent == [] for transport in transports)


async def test_shard_fora_da_topologia_erro(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Shard 3 numa topologia de 2 é erro de quem configurou — na cara,
    com as válidas na mensagem."""
    with pytest.raises(ValueError, match=r"v[áa]lidas: 0\.\.1"):
        make_manager(
            com_hello_e_ready(1),
            clock=clock,
            sleeper=sleeper,
            shard_ids=(0, 3),
            gateway_information=gateway_info(2),
        )


async def test_max_concurrency_alimenta_throttler(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Um throttler **só**, compartilhado; bucket é `shard % max_concurrency`."""
    manager = make_manager(
        com_hello_e_ready(3),
        clock=clock,
        sleeper=sleeper,
        gateway_information=gateway_info(3, max_concurrency=2),
    )

    throttler = manager.shards[0]._throttler
    assert throttler is manager.shards[1]._throttler is manager.shards[2]._throttler
    assert throttler.bucket_for(0) == 0
    assert throttler.bucket_for(1) == 1
    assert throttler.bucket_for(2) == 0


# ---------------------------------------------------------------------------
# Ciclo de vida em conjunto
# ---------------------------------------------------------------------------


async def test_shards_em_paralelo_chegam_ao_ready(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Todas conectam juntas; o manager só fica pronto com **todas**."""
    transports = com_hello_e_ready(3)
    avisos: list[bool] = []
    manager = make_manager(
        transports,
        clock=clock,
        sleeper=sleeper,
        gateway_information=gateway_info(3),
        on_ready=lambda: avisos.append(True),
    )
    task = asyncio.create_task(manager.connect())

    await settle(600)

    assert manager.ready
    # O aviso de "todas prontas" é um só, não um por shard.
    assert avisos == [True]

    for shard_id, transport in enumerate(transports):
        identify = next(f for f in transport.sent if f["op"] == GatewayOpcode.IDENTIFY)
        assert identify["d"]["shard"] == [shard_id, 3]

    await manager.close()
    await task


async def test_shard_com_sessao_valida_nao_identifica(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """Sessão no store → RESUME nas duas, e nem um IDENTIFY é gastado."""
    store = InMemorySessionStore()
    for shard_id in (0, 1):
        await store.update(
            shard_id,
            SessionInfo.from_ready(
                session_id=f"sessao-{shard_id}",
                sequence=7,
                resume_url="wss://gateway.discord.gg",
                shard_id=shard_id,
                shard_count=2,
            ),
        )
    transports = []
    for _ in range(2):
        transport = FakeGatewayTransport()
        transport.feed_payload(hello())
        transport.feed_payload(resumed())
        transports.append(transport)

    manager = make_manager(
        transports,
        clock=clock,
        sleeper=sleeper,
        session_store=store,
        gateway_information=gateway_info(2),
    )
    task = asyncio.create_task(manager.connect())

    await settle(600)

    assert manager.ready
    for transport in transports:
        assert GatewayOpcode.RESUME in transport.opcodes
        assert GatewayOpcode.IDENTIFY not in transport.opcodes

    await manager.close()
    await task


async def test_falha_fatal_num_shard_fecha_as_outras(
    clock: FakeClock, sleeper: FakeSleeper
) -> None:
    """4004 numa shard derruba o manager inteiro: o erro **original**
    sobe, e as outras fecham na hora. Um bot meio ligado é pior que um
    desligado — o orquestrador reinicia, e o identify novo resolve."""
    boa0, boa1 = com_hello_e_ready(2)
    morrendo = FakeGatewayTransport()
    morrendo.feed_payload(hello())
    morrendo.drop(code=4004, reason="token inválido")

    manager = make_manager(
        [boa0, morrendo, boa1],
        clock=clock,
        sleeper=sleeper,
        gateway_information=gateway_info(3),
    )
    task = asyncio.create_task(manager.connect())

    with pytest.raises(FatalGatewayError) as excinfo:
        await asyncio.wait_for(task, timeout=2.0)

    assert excinfo.value.code == 4004
    assert boa0.closes and boa1.closes


async def test_close_fecha_todas_sem_task_orfa(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Shutdown limpo: todas as shards fecham, nenhuma task sobra."""
    transports = com_hello_e_ready(2)
    manager = make_manager(
        transports, clock=clock, sleeper=sleeper, gateway_information=gateway_info(2)
    )
    task = asyncio.create_task(manager.connect())
    await settle(600)
    assert manager.ready

    await manager.close()
    await task

    assert all(transport.closes for transport in transports)
    assert manager._tarefas == {}
    assert all(shard.status is GatewayStatus.CLOSED for shard in manager.shards)


# ---------------------------------------------------------------------------
# Operações: latência, presença, membros
# ---------------------------------------------------------------------------


async def test_latency_e_media_das_shards(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Média das shards com medição; `None` sem nenhuma — e nunca zero."""
    manager = make_manager(
        com_hello_e_ready(3), clock=clock, sleeper=sleeper, gateway_information=gateway_info(3)
    )
    shard0, shard1, _ = manager.shards
    shard0._heartbeat.state.latency_ms = 10.0
    shard1._heartbeat.state.latency_ms = 20.0

    assert manager.latency == pytest.approx(15.0)

    shard0._heartbeat.state.latency_ms = None
    shard1._heartbeat.state.latency_ms = None
    assert manager.latency is None


async def test_update_presence_subset(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Subset manda só na escolhida; shard fora do manager é erro."""
    transports = com_hello_e_ready(2)
    manager = make_manager(
        transports, clock=clock, sleeper=sleeper, gateway_information=gateway_info(2)
    )
    task = asyncio.create_task(manager.connect())
    await settle(600)
    assert manager.ready

    await manager.update_presence(status="idle", shard_ids=(1,))

    assert GatewayOpcode.PRESENCE_UPDATE not in transports[0].opcodes
    assert GatewayOpcode.PRESENCE_UPDATE in transports[1].opcodes

    with pytest.raises(LifecycleError, match="5"):
        await manager.update_presence(shard_ids=(5,))

    await manager.close()
    await task


async def test_request_members_roteia_por_guild(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """`shard = (guild_id >> 22) % shards`: a guild pertence à shard 1 e
    o manager só tem a 0 — o erro nomeia a shard certa, que é a conta
    que o discord.js faz."""
    manager = make_manager(
        com_hello_e_ready(1),
        clock=clock,
        sleeper=sleeper,
        shard_ids=(0,),
        gateway_information=gateway_info(2),
    )
    guild_na_shard_1 = 7 << 22  # >> 22 = 7; 7 % 2 = 1

    with pytest.raises(LifecycleError, match="shard 1"):
        await manager.request_guild_members(guild_na_shard_1)
