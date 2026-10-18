"""Request Guild Members (op 8) — o `guild.members.fetch()` em payload cru.

O Discord entrega membros de uma guild aos pedaços: manda-se um frame
op 8 com um nonce, e o servidor responde com vários
`GUILD_MEMBERS_CHUNK` carregando o mesmo nonce, até terminar. Este
módulo é a correlação — o que transforma "vários eventos soltos" em
"um pedido que termina" — e nada mais. Os chunks continuam sendo
entregues como evento cru em `on_event` do jeito que sempre foram;
quem só quer o evento não paga nada por isto.

As três regras vêm do `GuildMemberManager.js` do discord.js, com uma
melhoria deliberada:

* **nonce** de no máximo 32 caracteres (`MemberFetchNonceLength`) —
  acima disso o frame morre no outro lado, então a recusa acontece
  aqui, com `ValueError`, e não como close code 4002/;
* **prazo** de 120s **renovado a cada chunk** (`:243, 264-267`) — um
  servidor grande manda vários chunks demorados, e cada um prova que a
  conexão ainda está viva; esgotar é "parou de andar", não "grande
  demais";
* **conclusão** quando o chunk tem menos de 1000 membros, ou o `limit`
  pedido já foi entregue, ou chegou ao último pedaço (`:278-281`).

A melhoria: o discord.js não limita quantos pedidos op 8 ficam
pendentes ao mesmo tempo (só incrementa max-listeners). Aqui há teto
(`MAX_PENDING_REQUESTS`) — regra §5: fila tem fim, e enfileirar dez
pedidos de membros que ninguém vai consumir é só memória parada.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from kryncord.errors import (
    MemberRequestRateLimited,
    MemberRequestTimeout,
    TooManyMemberRequests,
)
from kryncord.logging import get_logger

log = get_logger("gateway.members")

#: Teto do Discord para o nonce de um pedido op 8. O hex de um uuid4
#: tem exatamente 32 caracteres, que é o default daqui.
MAX_NONCE_LENGTH = 32

#: Prazo do pedido, em segundos, renovado a cada chunk recebido.
CHUNK_TIMEOUT = 120.0

#: Um chunk com menos membros que isto é o último — o Discord fatia em
#: pedaços de até 1000, então veio menos porque não há mais o que vir.
CHUNK_COMPLETE_THRESHOLD = 1000

#: Teto de pedidos simultâneos por conexão. Melhoria sobre o discord.js
#: (ver o docstring do módulo); regra §5.
MAX_PENDING_REQUESTS = 5

#: Agenda um callback para `delay` segundos à frente e devolve o que
#: cancela o agendamento.
#:
#: Injetado de propósito: o padrão usa `loop.call_later`, que mede
#: segundos de verdade — e um teste de timeout não pode esperar 120s de
#: relógio real para ver o que faz. O timer falso do teste guarda o
#: atraso e dispara quando o teste manda.
Timer = Callable[[float, Callable[[], None]], Callable[[], None]]


def _loop_timer(delay: float, callback: Callable[[], None]) -> Callable[[], None]:
    """Timer padrão: `loop.call_later`. Precisa de task viva rodando."""
    handle = asyncio.get_running_loop().call_later(delay, callback)
    return handle.cancel


@dataclass(frozen=True, slots=True)
class MemberChunk:
    """Um `GUILD_MEMBERS_CHUNK` já fatiado e validado."""

    members: list[dict[str, Any]]
    chunk_index: int
    chunk_count: int
    nonce: str
    not_found: list[str] = field(default_factory=list)

    @classmethod
    def from_dispatch(cls, data: Mapping[str, Any]) -> MemberChunk | None:
        """Parse do corpo cru. `None` quando não tem forma de chunk.

        Corpo inesperado não é erro daqui: o evento é do Discord e o
        passthrough para `on_event` continua obrigatório. Quem está
        correlacionando pedido é que decide o que fazer com forma
        inesperada — e a decisão é "não é meu".
        """
        members = data.get("members")
        index = data.get("chunk_index")
        count = data.get("chunk_count")
        nonce = data.get("nonce")
        if (
            not isinstance(members, list)
            or isinstance(index, bool)
            or not isinstance(index, int)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or not isinstance(nonce, str)
        ):
            return None

        not_found = data.get("not_found")
        return cls(
            members=cast("list[dict[str, Any]]", members),
            chunk_index=index,
            chunk_count=count,
            nonce=nonce,
            not_found=cast("list[str]", not_found) if isinstance(not_found, list) else [],
        )


@dataclass(slots=True)
class _Pedido:
    """Um pedido aberto: o nonce que o Discord ecoa e o futuro que
    espera os chunks."""

    nonce: str
    guild_id: str
    limit: int
    futuro: asyncio.Future[list[dict[str, Any]]]
    timeout: float
    membros: list[dict[str, Any]] = field(default_factory=list)
    cancelar_timeout: Callable[[], None] | None = None


class MemberChunkTracker:
    """Correlaciona pedidos op 8 com os `GUILD_MEMBERS_CHUNK` de volta.

    Objeto puro + futures do event loop — sem task própria, sem laço, sem
    espera. O tempo vive no timer injetado, renovado a cada chunk; este
    objeto só reage a quem o chama (`abrir`, `on_chunk`,
    `on_rate_limited`). É o desenho que deixa o teste determinístico e o
    shutdown limpo: `close()` cancela os futuros e para os relógios, e
    ninguém fica esperando chunk de um socket que já morreu.
    """

    def __init__(self, *, timer: Timer | None = None) -> None:
        self._timer: Timer = _loop_timer if timer is None else timer
        self._pendentes: dict[str, _Pedido] = {}

    @property
    def pendentes(self) -> int:
        """Quantos pedidos estão abertos agora."""
        return len(self._pendentes)

    def abrir(
        self,
        guild_id: int | str,
        *,
        limit: int = 0,
        nonce: str | None = None,
        timeout: float | None = None,
    ) -> _Pedido:
        """Abre um pedido e devolve o que é preciso para enviá-lo.

        `nonce` ausente vira uuid de 32 chars; acima do teto do Discord a
        recusa é aqui, com `ValueError`, e não como close code do outro
        lado. `timeout=None` usa os 120s do módulo.
        """
        if len(self._pendentes) >= MAX_PENDING_REQUESTS:
            raise TooManyMemberRequests(
                f"{len(self._pendentes)} pedidos de membros já abertos "
                f"(teto: {MAX_PENDING_REQUESTS}) — espere um terminar antes de abrir outro."
            )

        resolvido = uuid.uuid4().hex if nonce is None else nonce
        if len(resolvido) > MAX_NONCE_LENGTH:
            raise ValueError(
                f"nonce de {len(resolvido)} caracteres; o máximo do Discord é {MAX_NONCE_LENGTH}."
            )

        pedido = _Pedido(
            nonce=resolvido,
            guild_id=str(guild_id),
            limit=limit,
            futuro=asyncio.get_running_loop().create_future(),
            timeout=CHUNK_TIMEOUT if timeout is None else timeout,
        )
        self._pendentes[resolvido] = pedido
        self._agendar_timeout(pedido)
        return pedido

    def on_chunk(self, data: Any) -> bool:
        """Alimenta um `GUILD_MEMBERS_CHUNK`. Devolve `True` se era nosso.

        Chunk de nonce desconhecido devolve `False` e não mexe em nada —
        o chamador faz o passthrough para `on_event` como sempre fez.
        Este método nunca engole evento de ninguém.
        """
        if not isinstance(data, Mapping):
            return False
        chunk = MemberChunk.from_dispatch(data)
        if chunk is None:
            return False

        pedido = self._pendentes.get(chunk.nonce)
        if pedido is None:
            return False

        pedido.membros.extend(chunk.members)
        # Cada chunk renova o relógio por inteiro: o que esgota é pedido
        # parado, não servidor grande — GuildMemberManager.js:264-267.
        self._agendar_timeout(pedido)

        if self._completo(pedido, chunk):
            self._concluir(pedido)
        return True

    def on_rate_limited(self, data: Any) -> bool:
        """Trata um dispatch `RATE_LIMITED`. Devolve `True` se era nosso.

        O nonce do pedido vem em `d.meta.nonce` — o mesmo caminho que o
        `RATE_LIMITED.js` do discord.js segue. Rejeita o futuro com o
        `retry_after` que o Discord mandou, para quem chamou poder tentar
        de novo na hora certa.
        """
        if not isinstance(data, Mapping):
            return False
        meta = data.get("meta")
        if not isinstance(meta, Mapping) or not isinstance(meta.get("nonce"), str):
            return False

        pedido = self._pendentes.pop(meta["nonce"], None)
        if pedido is None:
            return False
        if pedido.cancelar_timeout is not None:
            pedido.cancelar_timeout()

        retry_after = data.get("retry_after", 0.0)
        if isinstance(retry_after, bool) or not isinstance(retry_after, (int, float)):
            retry_after = 0.0
        if not pedido.futuro.done():
            pedido.futuro.set_exception(
                MemberRequestRateLimited(
                    f"Gateway recusou o pedido de membros da guild {pedido.guild_id}: "
                    f"teto de pedidos atingido. Tente de novo em {retry_after:.1f}s.",
                    retry_after=float(retry_after),
                )
            )
        return True

    def abortar(self, nonce: str) -> None:
        """Descarta um pedido sem esperar os chunks — envio falhou no meio.

        Sem isto, o futuro ficaria esperando chunk que nunca vem, e o
        asyncio reclamaria de "exception never retrieved" no GC — um
        aviso tardio que ninguém associa ao envio que falhou.
        """
        pedido = self._pendentes.pop(nonce, None)
        if pedido is None:
            return
        if pedido.cancelar_timeout is not None:
            pedido.cancelar_timeout()
        if not pedido.futuro.done():
            pedido.futuro.cancel()

    def close(self) -> None:
        """Cancela todos os pendentes — shutdown limpo, regras §5."""
        for pedido in self._pendentes.values():
            if pedido.cancelar_timeout is not None:
                pedido.cancelar_timeout()
            if not pedido.futuro.done():
                pedido.futuro.cancel()
        self._pendentes.clear()

    @staticmethod
    def _completo(pedido: _Pedido, chunk: MemberChunk) -> bool:
        """Regra de conclusão do discord.js (`GuildMemberManager.js:278-281`)."""
        if len(chunk.members) < CHUNK_COMPLETE_THRESHOLD:
            return True
        if pedido.limit > 0 and len(pedido.membros) >= pedido.limit:
            return True
        return chunk.chunk_index == chunk.chunk_count - 1

    def _concluir(self, pedido: _Pedido) -> None:
        """Entrega a soma dos chunks e limpa o pedido."""
        if pedido.cancelar_timeout is not None:
            pedido.cancelar_timeout()
        self._pendentes.pop(pedido.nonce, None)
        if not pedido.futuro.done():
            pedido.futuro.set_result(pedido.membros)

    def _agendar_timeout(self, pedido: _Pedido) -> None:
        """(Re)arma o relógio do pedido — na abertura e a cada chunk."""
        if pedido.cancelar_timeout is not None:
            pedido.cancelar_timeout()

        def expirou() -> None:
            if pedido.futuro.done():
                return
            log.warning(
                "Pedido de membros da guild %s esgotou %.0fs sem chunk — cancelando.",
                pedido.guild_id,
                pedido.timeout,
            )
            self._pendentes.pop(pedido.nonce, None)
            pedido.futuro.set_exception(
                MemberRequestTimeout(
                    f"Nenhum `GUILD_MEMBERS_CHUNK` da guild {pedido.guild_id} em "
                    f"{pedido.timeout:.0f}s — pedido cancelado."
                )
            )

        pedido.cancelar_timeout = self._timer(pedido.timeout, expirou)
