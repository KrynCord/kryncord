"""Fixtures compartilhadas.

Regra do projeto: nenhum teste toca a rede. Transportes são simulados.

Também nenhum teste **dorme**. Um teste de rate limit que espera 30
segundos não é teste, é build — então `FakeClock` e `fake_sleeper`
substituem relógio e espera, e registram o que teria acontecido.
"""

from __future__ import annotations

import asyncio
import json
import zlib
from dataclasses import dataclass
from typing import Any

import pytest

from kryncord import __version__
from kryncord.enums import GatewayOpcode
from kryncord.errors import ConnectionClosedError
from kryncord.gateway.payloads import Payload


@pytest.fixture
def version() -> str:
    return __version__


class FakeClock:
    """Relógio monotônico controlado: só anda quando mandam."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


class FakeSleeper:
    """Substitui `asyncio.sleep`: não espera, só anota e avança o relógio.

    Avançar o relógio aqui é o que torna o teste determinístico: o
    rate limit calcula "esperar 5s", o sleeper anota 5 e anda 5 — então a
    próxima iteração já vê a janela zerada.

    O `asyncio.sleep(0)` no fim devolve o controle ao event loop. Sem
    ele, uma task que só chama o sleeper nunca suspende de verdade, e um
    heartbeat rodando em laço fechado giraria para sempre sem dar chance
    ao teste de pará-lo — o teste não travaria por lentidão, travaria
    por nunca voltar. Ceder uma vez por espera é o mínimo para que
    tarefas concorrentes (heartbeat, pump de eventos) convivam.
    """

    def __init__(self, clock: FakeClock | None = None) -> None:
        self.calls: list[float] = []
        self._clock = clock

    def total(self) -> float:
        return sum(self.calls)

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self._clock is not None and seconds > 0:
            self._clock.advance(seconds)
        await asyncio.sleep(0)


@pytest.fixture
def sleeper(clock: FakeClock) -> FakeSleeper:
    return FakeSleeper(clock)


@dataclass(frozen=True, slots=True)
class _SocketClosed:
    """Sentinela na fila: o outro lado encerrou a conexão."""

    code: int | None
    reason: str


class FakeGatewayTransport:
    """`GatewayTransport` simulado — uma fila de frames, sem rede.

    O truque está no `recv()`: quando a fila esvazia ele **bloqueia**,
    que é o que um socket real faz. É isso que devolve o controle ao
    teste — o pump para, o teste injeta o próximo frame (ou fecha a
    conexão), e o pump continua de onde parou.

    `auto_ack` manda um `HEARTBEAT_ACK` de volta quando vê um
    `HEARTBEAT`. O Discord faz exatamente isso, e sem imitar o
    comportamento o heartbeat declararia a conexão zumbi já na primeira
    batida — faltaria o ACK entre o envio e a próxima checagem.

    Quando a URL pede `compress=zlib-stream`, os frames de saída são
    comprimidos com um `compressobj` persistente — só assim o
    `FrameDecoder` do outro lado tem algo real para descomprimir.
    """

    def __init__(self, *, auto_ack: bool = True) -> None:
        self.auto_ack = auto_ack
        self.connected_urls: list[str] = []
        self.sent: list[dict[str, Any]] = []
        self.closes: list[tuple[int, str]] = []
        self.connect_error: BaseException | None = None
        self._queue: asyncio.Queue[str | bytes | _SocketClosed] = asyncio.Queue()
        self._scripts: list[list[str | bytes | _SocketClosed]] = []
        self._script_open = False
        self._compressor: zlib.Compress | None = None
        self._attempts = 0
        self._closed = False

    # ------------------------------------------------------------------
    # Roteirização — o que o "Discord simulado" faz
    # ------------------------------------------------------------------

    def feed(self, frame: str | bytes) -> None:
        """Joga um frame cru na fila da conexão atual."""
        self._queue.put_nowait(frame)

    def feed_payload(self, payload: Payload) -> None:
        """Serializa um `Payload` e joga na fila atual."""
        self.feed(payload.encode())

    def drop(self, code: int | None = 1000, reason: str = "closed by Discord") -> None:
        """Simula o Discord encerrando a conexão atual com `code`."""
        self._queue.put_nowait(_SocketClosed(code=code, reason=reason))

    def feed_next(self, frame: str | bytes) -> None:
        """Enfileira um frame para a **próxima** tentativa de conexão.

        Sem isto, o pump da tentativa 1 leria o `HELLO` da tentativa 2
        como um opcode surpresa e o teste falharia num lugar que não tem
        nada a ver com o que ele queria verificar. Cada tentativa é um
        socket novo, e em socket novo nada do anterior atravessa.

        Um `drop_next` **fecha** o roteirismo daquela tentativa; o que
        vier depois já pertence à tentativa seguinte. É assim que um
        teste scripta três ciclos de queda de uma vez só.
        """
        self._open_script().append(frame)

    def feed_payload_next(self, payload: Payload) -> None:
        """Igual a `feed_next`, já serializado."""
        self.feed_next(payload.encode())

    def drop_next(self, code: int | None = 1000, reason: str = "closed by Discord") -> None:
        """Encerramento roteirizado para a próxima tentativa."""
        self._open_script().append(_SocketClosed(code=code, reason=reason))
        self._script_open = False

    def _open_script(self) -> list[str | bytes | _SocketClosed]:
        if not self._script_open or not self._scripts:
            self._scripts.append([])
            self._script_open = True
        return self._scripts[-1]

    def _maybe_compress(self, frame: str | bytes) -> str | bytes:
        if self._compressor is None or isinstance(frame, bytes):
            return frame
        compressed = self._compressor.compress(frame.encode())
        return compressed + self._compressor.flush(zlib.Z_SYNC_FLUSH)

    # ------------------------------------------------------------------
    # GatewayTransport
    # ------------------------------------------------------------------

    async def connect(self, url: str) -> None:
        if self.connect_error is not None:
            error = self.connect_error
            self.connect_error = None
            raise error

        self.connected_urls.append(url)
        self._closed = False
        self._attempts += 1
        # Um contexto de compressão por conexão: é o que o Discord faz,
        # e reaproveitar entre sockets daria lixo no primeiro frame.
        self._compressor = zlib.compressobj() if "compress=zlib-stream" in url else None
        if self._attempts > 1:
            # Socket novo: o que sobrou do anterior não atravessa, e o
            # script desta tentativa entra agora. Sem script, a fila
            # fica vazia e o `recv()` bloqueia — um socket que aceita a
            # conexão e fica calado.
            self._queue = asyncio.Queue()
            if self._scripts:
                for item in self._scripts.pop(0):
                    self._queue.put_nowait(item)

    async def send(self, data: str) -> None:
        if self._closed:
            raise ConnectionClosedError("Envio em conexão já fechada.")
        payload: dict[str, Any] = json.loads(data)
        self.sent.append(payload)
        if self.auto_ack and payload.get("op") == GatewayOpcode.HEARTBEAT:
            self.feed_payload(Payload(op=GatewayOpcode.HEARTBEAT_ACK))

    async def recv(self) -> str | bytes:
        item = await self._queue.get()
        if isinstance(item, _SocketClosed):
            raise ConnectionClosedError(
                f"Conexão simulada encerrada (código {item.code}).",
                code=item.code,
                reason=item.reason,
            )
        # A compressão acontece na entrega, não no enqueue: nos testes o
        # frame é enfileirado antes do `connect()` criar o contexto.
        return self._maybe_compress(item)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self._closed:
            return
        self._closed = True
        self.closes.append((code, reason))
        # Um `recv()` pendurado tem que acordar. É isso que fechar um
        # socket real faz com quem está lendo.
        self._queue.put_nowait(_SocketClosed(code=code, reason=reason))

    @property
    def closed(self) -> bool:
        return self._closed

    # ------------------------------------------------------------------
    # Atalhos de asserção
    # ------------------------------------------------------------------

    @property
    def opcodes(self) -> list[int]:
        """Opcodes que enviamos, na ordem — olhar a conversa inteira."""
        return [int(payload["op"]) for payload in self.sent]

    @property
    def identify(self) -> dict[str, Any]:
        """O payload do `IDENTIFY`, quebrando se não houve."""
        for payload in self.sent:
            if payload["op"] == GatewayOpcode.IDENTIFY:
                return payload["d"]
        raise AssertionError(f"Nenhum IDENTIFY enviado; opcodes: {self.opcodes}")

    @property
    def resume(self) -> dict[str, Any]:
        """O payload do `RESUME`, quebrando se não houve."""
        for payload in self.sent:
            if payload["op"] == GatewayOpcode.RESUME:
                return payload["d"]
        raise AssertionError(f"Nenhum RESUME enviado; opcodes: {self.opcodes}")
