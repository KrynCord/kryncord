"""A conexão WebSocket, e o teto de envio que ela precisa respeitar.

Duas coisas moram aqui, e as duas são sobre o **socket**:

`GatewayTransport` é o contrato. `WebSocketConnection` é a implementação
com `websockets`. O contrato existe para que `gateway/client.py` possa
ser testado sem rede nenhuma — `FakeTransport` implementa as mesmas
cinco assinaturas e o ciclo de vida inteiro roda em memória.

`GatewaySendRateLimit` é o teto de **115 frames por 60 segundos** que o
Discord impõe por conexão. Ele fica no caminho de envio, e não no
transporte, de propósito: assim vale para qualquer transporte, inclusive
o simulado dos testes. Se ficasse dentro de `WebSocketConnection`, o
teste do rate limit precisaria de um socket de verdade — e aí o teste
tocaria na rede, que é a única coisa que este projeto proíbe.

Por que desligar o ping do `websockets` (``ping_interval=None``):

O `websockets` manda ping de controle a cada 20s por conta própria. O
Discord já tem o heartbeat de aplicação, que é o que **importa** — o
ACK dele é o sinal de que a sessão está viva. Ter os dois significa
dois mecanismos decidindo quando fechar, e o de controle pode derrubar
uma conexão saudável só porque o processo ficou 20s travado no GC.
A detecção de conexão zumbi já cobre o caso de TCP silenciosamente
morto: mandamos heartbeat, o ACK não chega, e fechamos.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from kryncord.errors import ConnectionClosedError
from kryncord.internal.timing import Clock, Sleeper, monotonic_clock, real_sleep

# --- constantes de tempo, em segundos -------------------------------------
# As três primeiras vêm do DefaultWebSocketManagerOptions do discord.js:
# handshakeTimeout, helloTimeout, readyTimeout.

#: Tempo para o socket abrir (TCP + TLS + upgrade).
HANDSHAKE_TIMEOUT = 30.0
#: Tempo para o primeiro frame (o `HELLO`) depois de aberto.
HELLO_TIMEOUT = 60.0
#: Tempo entre mandar Identify e receber o `READY`.
READY_TIMEOUT = 15.0
#: Tempo para fechar a conexão de forma ordenada.
CLOSE_TIMEOUT = 10.0

#: Tamanho máximo de um frame. O default do `websockets` é 1 MiB, que
#: estoura num `GUILD_CREATE` de servidor grande. 4 MiB dá folga sem
#: deixar um frame malicioso encher a memória.
MAX_MESSAGE_SIZE = 4 * 1024 * 1024

#: Frames por janela de envio, e o tamanho da janela (segundos).
SEND_LIMIT = 115
SEND_WINDOW = 60.0
#: Folga sorteada quando a janela estoura. Segundos.
SEND_JITTER = 1.5


@runtime_checkable
class GatewayTransport(Protocol):
    """O que `GatewayClient` precisa de um socket. Nada mais.

    `recv()` levanta `ConnectionClosedError` quando a conexão acaba —
    com o código de fechamento quando o Discord mandou um, `None` quando
    a rede caiu sem aviso. Essa distinção é o insumo de
    `reconnect.classify_close`, que decide entre resume e identify.
    """

    async def connect(self, url: str) -> None:
        """Abre a conexão. Levanta `OSError`/`TimeoutError` se não abrir."""
        ...

    async def send(self, data: str) -> None:
        """Manda um frame de texto já serializado."""
        ...

    async def recv(self) -> str | bytes:
        """Recebe o próximo frame. Levanta `ConnectionClosedError` se fechou."""
        ...

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Fecha de forma ordenada. Idempotente: fechar duas vezes é ok."""
        ...

    @property
    def closed(self) -> bool:
        """`True` depois que `recv()` não vai mais devolver nada."""
        ...


class WebSocketConnection:
    """`GatewayTransport` sobre a biblioteca `websockets`."""

    def __init__(
        self,
        *,
        handshake_timeout: float = HANDSHAKE_TIMEOUT,
        close_timeout: float = CLOSE_TIMEOUT,
        max_message_size: int = MAX_MESSAGE_SIZE,
    ) -> None:
        self._handshake_timeout = handshake_timeout
        self._close_timeout = close_timeout
        self._max_message_size = max_message_size
        # websockets.ClientConnection | None — tipado como Any para não
        # puxar o tipo concreto da lib para o escopo de módulo.
        self._ws: object | None = None
        #: Código que *nós* mandamos em `close()`. Serve de fallback quando
        #: o socket morre sem devolver frame de fechamento do outro lado.
        self._local_close_code: int | None = None

    async def connect(self, url: str) -> None:
        # Import local: quem importa `gateway` não deveria pagar o custo
        # de carregar a lib de WebSocket se nunca for abrir uma conexão.
        from websockets.asyncio.client import connect as ws_connect

        self._local_close_code = None
        self._ws = await ws_connect(
            url,
            open_timeout=self._handshake_timeout,
            close_timeout=self._close_timeout,
            max_size=self._max_message_size,
            # O Discord não usa permessage-deflate; a compressão deles é
            # de aplicação, negociada na query string.
            compression=None,
            # Ver docstring do módulo: o heartbeat de aplicação é quem
            # decide, não o ping de controle desta lib.
            ping_interval=None,
        )

    async def send(self, data: str) -> None:
        await self._require().send(data)  # type: ignore[attr-defined]

    async def recv(self) -> str | bytes:
        from websockets.exceptions import ConnectionClosed

        ws = self._require()
        try:
            return await ws.recv()  # type: ignore[attr-defined, no-any-return]
        except ConnectionClosed as exc:
            # `rcvd` é um `frames.Close | None`, não um `int`: o código
            # mora em `.code`. O `.code` direto da exceção está
            # deprecado pela lib e emite aviso.
            code = exc.rcvd.code if exc.rcvd is not None else self._local_close_code
            reason = exc.rcvd.reason if exc.rcvd is not None else ""
            raise ConnectionClosedError(
                f"Conexão com o Gateway encerrada: código {code}, motivo {reason!r}",
                code=code,
                reason=reason,
            ) from exc

    async def close(self, code: int = 1000, reason: str = "") -> None:
        ws = self._ws
        if ws is None:
            return
        self._local_close_code = code
        try:
            await ws.close(code, reason)  # type: ignore[attr-defined]
        finally:
            self._ws = None

    @property
    def closed(self) -> bool:
        from websockets.protocol import State

        ws = self._ws
        if ws is None:
            return True
        return ws.state is State.CLOSED  # type: ignore[attr-defined]

    def _require(self) -> object:
        ws = self._ws
        if ws is None:
            raise ConnectionClosedError(
                "Conexão não está aberta — chame `connect()` antes.",
                code=self._local_close_code,
            )
        return ws


@dataclass(slots=True)
class GatewaySendRateLimit:
    """Teto client-side de 115 frames por janela de 60 segundos.

    O Discord **não** avisa quando isso estoura: a conexão simplesmente
    cai. Esperar o socket fechar para descobrir seria pagar round-trip
    por um erro que dá para não cometer.

    A conta é a do discord.js: quando o envio seguinte seria o 115º,
    dorme até a janela virar, mais um pouco de sorte. O ``while`` (e não
    um ``if``) existe porque a espera pode não bastar — relógio que atrasa,
    jitter curto — e nesse caso espera de novo em vez de estourar o teto.

    O sentinela é ``sent + 1 >= limit``, copiado do ``WebSocketShard``:
    o 115º envio é o que espera, então cabem 114 por janela. É folga,
    não exatidão — o limite documentado do Discord é 120.

    Duas mecânicas complementares vêm do mesmo ``WebSocketShard``:

    * ``acquire(important=True)`` — heartbeat (op 1), identify (op 2) e
      resume (op 6) **não** contam no budget. São os
      ``ImportantGatewayOpcodes`` do discord.js: um bot com heartbeat de
      ~41s gastaria dois frames da janela por minuto à toa, contando
      batimento como evento.
    * ``reset()`` — o teto é **por conexão**. Um socket novo tem budget
      novo do Discord; segurar o contador da conexão anterior seria
      pagar duas vezes por frames que nem foram na conexão nova. É o
      ``onopen`` do discord.js, que zera ``{sent, resetAt}`` em todo
      (re)connect.
    """

    limit: int = SEND_LIMIT
    window: float = SEND_WINDOW
    jitter: float = SEND_JITTER
    clock: Clock = field(default=monotonic_clock, repr=False)
    sleeper: Sleeper = field(default=real_sleep, repr=False)
    random: Callable[[], float] = field(default=random.random, repr=False)

    _reset_at: float = field(default=0.0, init=False, repr=False)
    _sent: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError(f"limit precisa ser ao menos 1, recebido {self.limit}")
        if self.window <= 0:
            raise ValueError(f"window precisa ser positiva, recebido {self.window}")
        if self.jitter < 0:
            raise ValueError(f"jitter não pode ser negativo, recebido {self.jitter}")
        self._reset_at = self.clock() + self.window

    async def acquire(self, *, important: bool = False) -> None:
        """Bloqueia até poder mandar um frame sem estourar o teto.

        ``important=True`` é o dos ops que o Discord não deduz do teto —
        ver a docstring da classe. Sai na hora, sem esperar e sem contar:
        só os frames de evento gastam budget.
        """
        while True:
            now = self.clock()
            if now >= self._reset_at:
                self._reset_at = now + self.window
                self._sent = 0

            if important or self._sent + 1 < self.limit:
                break

            wait = self._reset_at - now + self.random() * self.jitter
            await self.sleeper(wait)

        if not important:
            self._sent += 1

    def reset(self) -> None:
        """Abre uma janela nova — chamado a cada (re)connect.

        O teto é por conexão; ver a docstring da classe.
        """
        self._reset_at = self.clock() + self.window
        self._sent = 0

    @property
    def remaining(self) -> int:
        """Frames que ainda cabem na janela atual."""
        now = self.clock()
        if now >= self._reset_at:
            return self.limit - 1
        return max(0, (self.limit - 1) - self._sent)
