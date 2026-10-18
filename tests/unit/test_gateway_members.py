"""Request Guild Members (op 8): correlação, prazo e recusa.

O "Discord" aqui é o `MemberChunkTracker` alimentado à mão — nenhum
teste abre socket, e nenhum teste espera 120 segundos de relógio real:
o tempo é o timer falso, que guarda o atraso e dispara quando o teste
manda. Os dois testes de fio inteiro no fim usam o mesmo
`FakeGatewayTransport` do resto da suíte do gateway.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from kryncord.enums import GatewayOpcode
from kryncord.errors import (
    LifecycleError,
    MemberRequestRateLimited,
    MemberRequestTimeout,
    TooManyMemberRequests,
)
from kryncord.gateway.members import (
    CHUNK_TIMEOUT,
    MAX_NONCE_LENGTH,
    MAX_PENDING_REQUESTS,
    MemberChunkTracker,
)
from kryncord.gateway.payloads import Payload
from tests.conftest import FakeClock, FakeGatewayTransport, FakeSleeper
from tests.unit.test_gateway_client import (
    hello,
    make_gateway,
    ready,
    run_until_ready,
    settle,
)


@dataclass
class _Agendamento:
    """Um `call_later` guardado pelo `FakeTimer`."""

    delay: float
    callback: Callable[[], None]
    cancelado: bool = False

    def cancelar(self) -> None:
        self.cancelado = True


class FakeTimer:
    """`Timer` de teste: guarda o agendamento e dispara quando mandam.

    Cancelar é de verdade (o agendamento cancelado não dispara), que é
    a semântica do `loop.call_later` que o tracker assume.
    """

    def __init__(self) -> None:
        self.agendados: list[_Agendamento] = []

    def __call__(self, delay: float, callback: Callable[[], None]) -> Callable[[], None]:
        agendamento = _Agendamento(delay, callback)
        self.agendados.append(agendamento)
        return agendamento.cancelar

    def disparar_ativos(self) -> None:
        for agendamento in list(self.agendados):
            if not agendamento.cancelado:
                agendamento.callback()


def tracker() -> tuple[MemberChunkTracker, FakeTimer]:
    timer = FakeTimer()
    return MemberChunkTracker(timer=timer), timer


def chunk(
    nonce: str,
    *,
    membros: int = 0,
    index: int = 0,
    count: int = 1,
) -> dict[str, Any]:
    """Corpo cru de um `GUILD_MEMBERS_CHUNK`."""
    return {
        "members": [{"user": {"id": str(i)}} for i in range(membros)],
        "chunk_index": index,
        "chunk_count": count,
        "nonce": nonce,
    }


# ---------------------------------------------------------------------------
# Conclusão
# ---------------------------------------------------------------------------


async def test_conclusao_por_chunk_count_final() -> None:
    """`chunk_index == chunk_count - 1` completa o pedido.

    É o "cheguei no último pedaço" do discord.js — importa quando todo
    chunk cheio, o `limit` não foi atingido e ainda assim era o fim.
    """
    rastreio, _ = tracker()
    # `limit=0`: a regra do limite não pode completar antes da hora —
    # o que interessa aqui é só o "último pedaço".
    pedido = rastreio.abrir("100")

    assert rastreio.on_chunk(chunk(pedido.nonce, membros=1000, index=0, count=2))
    assert not pedido.futuro.done()

    assert rastreio.on_chunk(chunk(pedido.nonce, membros=1000, index=1, count=2))
    membros = await pedido.futuro

    assert len(membros) == 2000
    assert rastreio.pendentes == 0


async def test_conclusao_por_chunk_pequeno() -> None:
    """Chunk com menos de 1000 membros é o último — fim do pedido."""
    rastreio, _ = tracker()
    pedido = rastreio.abrir("100")

    assert rastreio.on_chunk(chunk(pedido.nonce, membros=10))
    assert len(await pedido.futuro) == 10


async def test_conclusao_por_limit_alcancado() -> None:
    """`limit` entregue completa mesmo com `count` dizendo que há mais.

    O caso que o discord.js cobre com `fetched >= limit`: pediu 1000,
    o primeiro chunk já trouxe 1000 — os pedaços seguintes não vêm, e
    esperar por eles seria esperar para sempre.
    """
    rastreio, _ = tracker()
    pedido = rastreio.abrir("100", limit=1000)

    assert rastreio.on_chunk(chunk(pedido.nonce, membros=1000, index=0, count=3))
    assert len(await pedido.futuro) == 1000


async def test_chunk_nonce_desconhecido_so_passa_adiante() -> None:
    """Chunk de nonce alheio não é nosso: `False` e nada muda.

    O evento continua indo para `on_event` como sempre — este tracker
    nunca engole chunk de ninguém.
    """
    rastreio, _ = tracker()
    pedido = rastreio.abrir("100")

    assert not rastreio.on_chunk(chunk("nonce-de-outro", membros=10))
    assert not pedido.futuro.done()
    assert rastreio.pendentes == 1


# ---------------------------------------------------------------------------
# Prazo
# ---------------------------------------------------------------------------


async def test_timeout_sem_chunk() -> None:
    """120s sem chunk → `MemberRequestTimeout`, e o pedido some."""
    rastreio, timer = tracker()
    pedido = rastreio.abrir("100")

    assert timer.agendados[0].delay == CHUNK_TIMEOUT
    timer.disparar_ativos()

    with pytest.raises(MemberRequestTimeout, match="100"):
        await pedido.futuro
    assert rastreio.pendentes == 0


async def test_timeout_renova_a_cada_chunk() -> None:
    """Chunk renova o relógio por inteiro — contagem não acumula.

    É o que separa "pedido parado" de "servidor grande": um guild de
    50 mil membros manda chunks por minutos, e cada um prova que a
    conexão ainda está viva.
    """
    rastreio, timer = tracker()
    # `limit=0` de novo: sem ele, o primeiro chunk de 1000 fecharia o
    # pedido pela regra do limite antes de qualquer renovação provar o
    # que veio provar.
    pedido = rastreio.abrir("100")

    primeiro = timer.agendados[0]
    rastreio.on_chunk(chunk(pedido.nonce, membros=1000, index=0, count=3))

    assert primeiro.cancelado
    assert len(timer.agendados) == 2
    assert timer.agendados[1].delay == CHUNK_TIMEOUT
    assert not pedido.futuro.done()

    rastreio.on_chunk(chunk(pedido.nonce, membros=10, index=1, count=3))
    assert len(await pedido.futuro) == 1010


# ---------------------------------------------------------------------------
# Recusas
# ---------------------------------------------------------------------------


async def test_rate_limited_rejeita_com_retry_after() -> None:
    """`RATE_LIMITED` com o nonce do pedido → erro com o `retry_after`."""
    rastreio, _ = tracker()
    pedido = rastreio.abrir("100")

    assert rastreio.on_rate_limited({"meta": {"nonce": pedido.nonce}, "retry_after": 4.2})

    with pytest.raises(MemberRequestRateLimited) as excinfo:
        await pedido.futuro
    assert excinfo.value.retry_after == pytest.approx(4.2)
    assert rastreio.pendentes == 0


async def test_rate_limited_de_outro_nao_mexe_no_nosso() -> None:
    """Nonce alheio no `RATE_LIMITED`: `False` e o pedido segue vivo."""
    rastreio, _ = tracker()
    pedido = rastreio.abrir("100")

    assert not rastreio.on_rate_limited({"meta": {"nonce": "outro"}, "retry_after": 1.0})
    assert not pedido.futuro.done()
    assert rastreio.pendentes == 1


async def test_nonce_ausente_gera_uuid_32_chars() -> None:
    """Nonce gerado tem exatamente os 32 caracteres que o Discord aceita."""
    rastreio, _ = tracker()
    pedido = rastreio.abrir("100")

    assert len(pedido.nonce) == MAX_NONCE_LENGTH == 32


async def test_nonce_longo_rejeitado() -> None:
    """33 caracteres já estouram o teto do Discord — recusa aqui."""
    rastreio, _ = tracker()

    with pytest.raises(ValueError, match="32"):
        rastreio.abrir("100", nonce="x" * (MAX_NONCE_LENGTH + 1))


async def test_teto_de_pedidos_simultaneos() -> None:
    """O 6º pedido recusa na cara — fila tem fim, regra §5."""
    rastreio, _ = tracker()
    for guild in range(MAX_PENDING_REQUESTS):
        rastreio.abrir(str(guild))

    with pytest.raises(TooManyMemberRequests, match="5"):
        rastreio.abrir("extra")

    rastreio.close()


async def test_close_cancela_pendentes() -> None:
    """Shutdown limpo: futuros cancelados, relógios parados, mapa vazio."""
    rastreio, timer = tracker()
    pedidos = [rastreio.abrir(str(guild)) for guild in range(3)]

    rastreio.close()

    assert rastreio.pendentes == 0
    assert all(agendamento.cancelado for agendamento in timer.agendados)
    for pedido in pedidos:
        with pytest.raises(asyncio.CancelledError):
            await pedido.futuro


# ---------------------------------------------------------------------------
# Fio inteiro (GatewayClient)
# ---------------------------------------------------------------------------


async def test_sem_sessao_erro_acionavel(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Pedido fora de sessão falha na cara, não vira frame perdido."""
    transport = FakeGatewayTransport()
    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)

    with pytest.raises(LifecycleError, match="READY"):
        await gateway.request_guild_members("1")


async def test_pedido_completo_pelo_gateway(clock: FakeClock, sleeper: FakeSleeper) -> None:
    """Fio inteiro: op 8 sai com o corpo certo, chunk volta, soma entrega."""
    transport = FakeGatewayTransport()
    transport.feed_payload(hello())
    transport.feed_payload(ready())
    gateway = make_gateway(transport, clock=clock, sleeper=sleeper)
    task = await run_until_ready(gateway)

    pedido = asyncio.create_task(gateway.request_guild_members("42", limit=1000))
    await settle()

    enviado = next(
        frame for frame in transport.sent if frame["op"] == GatewayOpcode.REQUEST_GUILD_MEMBERS
    )
    assert enviado["d"]["guild_id"] == "42"
    assert enviado["d"]["limit"] == 1000
    assert len(enviado["d"]["nonce"]) == 32

    transport.feed_payload(
        Payload(
            op=GatewayOpcode.DISPATCH,
            data=chunk(enviado["d"]["nonce"], membros=3, index=0, count=1),
            sequence=2,
            event_name="GUILD_MEMBERS_CHUNK",
        )
    )

    membros = await asyncio.wait_for(pedido, timeout=2.0)
    assert len(membros) == 3

    await gateway.close()
    await task
