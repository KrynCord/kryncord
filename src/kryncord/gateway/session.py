"""Informação de sessão, e onde guardá-la.

Um bot que desconecta e volta sem retomar a sessão perde eventos: o
Discord entrega tudo que aconteceu enquanto a sessão estava morta, ou
não entrega nada — dependendo de como a retomada é feita. Para retomar,
precisamos de três coisas guardadas:

* ``session_id`` — o Discord nos deu no ``READY``.
* ``sequence`` — o último número de evento que vimos. É o "continuar
  daqui" do ``RESUME``.
* ``resume_gateway_url`` — o ``READY`` manda uma URL específica para
  reconexão, e ela **não é** a do ``/gateway/bot``. Usar a base daria
  um 4009 (Session no longer valid) que parece bug nosso.

O `SessionStore` é uma interface por um motivo: em produção isso vive em
Redis ou no disco. Guardar em memória é o default honesto — sobrevive a
desconexão de rede, não a reinício de processo. Trocar é uma linha.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Tudo que o ``RESUME`` precisa, e o que decide se ele é possível."""

    session_id: str
    sequence: int
    resume_url: str
    shard_id: int
    shard_count: int

    @classmethod
    def from_ready(
        cls,
        *,
        session_id: str,
        sequence: int,
        resume_url: str,
        shard_id: int,
        shard_count: int,
    ) -> SessionInfo:
        return cls(
            session_id=session_id,
            sequence=sequence,
            resume_url=resume_url,
            shard_id=shard_id,
            shard_count=shard_count,
        )

    @classmethod
    def from_dispatch(
        cls, payload_data: Mapping[str, Any], *, sequence: int, shard_id: int, shard_count: int
    ) -> SessionInfo | None:
        """Monta a partir do corpo do ``READY``. ``None`` se faltar campo.

        Não valida com `raise`: um ``READY`` sem ``session_id`` é anomalia
        do Discord, e derrubar a conexão inteira por isso seria trocar um
        problema contornável por um fatal.
        """
        session_id = payload_data.get("session_id")
        resume_url = payload_data.get("resume_gateway_url")
        if not isinstance(session_id, str) or not isinstance(resume_url, str):
            return None
        return cls(
            session_id=session_id,
            sequence=sequence,
            resume_url=resume_url,
            shard_id=shard_id,
            shard_count=shard_count,
        )

    def can_resume_with(self, shard_count: int) -> bool:
        """Sessão só serve se a topologia de shards não mudou.

        Se o número de shards mudou, a sessão antiga pertence a uma
        divisão que não existe mais — o Discord a rejeitaria com
        ``invalid_session``. Melhor nem tentar: identify novo é mais
        rápido que um round-trip que termina em erro.
        """
        return self.shard_count == shard_count


class SessionStore(Protocol):
    """Onde as sessões vivem. Implementação padrão: em memória."""

    async def retrieve(self, shard_id: int) -> SessionInfo | None: ...

    async def update(self, shard_id: int, info: SessionInfo | None) -> None: ...


class InMemorySessionStore:
    """Sobrevive a desconexão, não a reinício de processo.

    É o default porque é o que funciona num exemplo de 10 linhas. Quem
    precisa de persistência real implementa `SessionStore` — o contrato
    tem dois métodos.
    """

    def __init__(self) -> None:
        self._sessions: dict[int, SessionInfo] = {}

    async def retrieve(self, shard_id: int) -> SessionInfo | None:
        return self._sessions.get(shard_id)

    async def update(self, shard_id: int, info: SessionInfo | None) -> None:
        if info is None:
            self._sessions.pop(shard_id, None)
        else:
            self._sessions[shard_id] = info

    def __len__(self) -> int:
        return len(self._sessions)

    def __contains__(self, shard_id: int) -> bool:
        return shard_id in self._sessions
