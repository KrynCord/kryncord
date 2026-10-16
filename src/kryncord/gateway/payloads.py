"""Modelo dos payloads do Gateway, com validação.

O Gateway fala JSON: ``{op, d, s, t}``. Quatro campos, e cada um tem uma
armadilha.

**``op`` é int, mas ``bool`` também é int em Python.** Sem checar,
``{"op": true}`` passaria e viraria ``op == 1`` (Heartbeat) — o parser
aceitaria um frame malformado e o bot mandaria heartbeat por engano.
Por isso a validação rejeita ``bool`` explicitamente.

**``s`` (sequence) é o coração do resume.** É o número de evento; se
perdermos, a sessão não dá para retomar e o Discord descarta. Guardamos
toda sequence que aparece, inclusive em dispatch que ninguém escuta.

**``t`` só existe em dispatch.** Em Heartbeat o Discord manda ``t: null``,
não omite — aceitar ambos, mas normalizar para ``None``.

Frames binários (compressão) e textos não-JSON caem em `GatewayError`,
que vira close code 4002 (Decode Error) no chamador.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.enums import GatewayOpcode
from kryncord.errors import GatewayError


@dataclass(frozen=True, slots=True)
class Payload:
    """Um frame do Gateway, já interpretado."""

    op: int
    data: Any = None
    sequence: int | None = None
    event_name: str | None = None

    @classmethod
    def decode(cls, raw: bytes | str) -> Payload:
        """Interpreta um frame. Levanta `GatewayError` se não for válido.

        Um frame malformado não pode estourar `json.JSONDecodeError`
        num lugar que ninguém captura — vira `GatewayError`, e o chamador
        fecha a conexão com 4002.
        """
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GatewayError(
                f"Frame do Gateway não é JSON válido: {exc}. Início: {raw[:120]!r}"
            ) from exc

        if not isinstance(data, dict):
            raise GatewayError(
                f"Frame do Gateway deveria ser objeto, veio {type(data).__name__}: "
                f"{str(data)[:120]!r}"
            )

        return cls._validated(data)

    @classmethod
    def _validated(cls, data: Mapping[str, Any]) -> Payload:
        op = data.get("op")
        # bool é subclasse de int — `{"op": true}` viraria Heartbeat.
        if isinstance(op, bool) or not isinstance(op, int):
            raise GatewayError(
                f"Campo `op` deveria ser inteiro, veio {op!r}. "
                "Frame malformado; fechar com 4002 (Decode Error)."
            )

        sequence = data.get("s")
        if sequence is not None and (isinstance(sequence, bool) or not isinstance(sequence, int)):
            raise GatewayError(f"Campo `s` deveria ser inteiro ou null, veio {sequence!r}.")

        event_name = data.get("t")
        if event_name is not None and not isinstance(event_name, str):
            raise GatewayError(f"Campo `t` deveria ser string ou null, veio {event_name!r}.")

        return cls(op=op, data=data.get("d"), sequence=sequence, event_name=event_name)

    def encode(self) -> str:
        """Serializa para envio. Campos nulos saem, como o Discord espera."""
        out: dict[str, Any] = {"op": self.op, "d": self.data}
        if self.sequence is not None:
            out["s"] = self.sequence
        if self.event_name is not None:
            out["t"] = self.event_name
        return json.dumps(out, separators=(",", ":"), ensure_ascii=False)

    # ------------------------------------------------------------------
    # Predicados — mais legíveis que comparar com o enum no meio do código
    # ------------------------------------------------------------------

    @property
    def is_dispatch(self) -> bool:
        return self.op == GatewayOpcode.DISPATCH

    @property
    def is_hello(self) -> bool:
        return self.op == GatewayOpcode.HELLO

    @property
    def is_heartbeat(self) -> bool:
        return self.op == GatewayOpcode.HEARTBEAT

    @property
    def is_heartbeat_ack(self) -> bool:
        return self.op == GatewayOpcode.HEARTBEAT_ACK

    @property
    def is_reconnect(self) -> bool:
        return self.op == GatewayOpcode.RECONNECT

    @property
    def is_invalid_session(self) -> bool:
        return self.op == GatewayOpcode.INVALID_SESSION

    @property
    def is_resumable(self) -> bool | None:
        """Só faz sentido em ``invalid_session``: o Discord diz se dá para
        retomar. `None` quando não é o opcode apropriado — e não `False`,
        porque `False` aqui significaria "o Discord disse que não dá".
        """
        if not self.is_invalid_session:
            return None
        if isinstance(self.data, bool):
            return self.data
        return False

    @property
    def heartbeat_interval_ms(self) -> float | None:
        """Só faz sentido em ``hello``."""
        if not self.is_hello or not isinstance(self.data, Mapping):
            return None
        interval = self.data.get("heartbeat_interval")
        if isinstance(interval, bool) or not isinstance(interval, (int, float)):
            return None
        return float(interval)

    @property
    def resume_gateway_url(self) -> str | None:
        """URL preferida nas reconexões, vinda do ``READY``."""
        if not (self.is_dispatch and self.event_name == "READY"):
            return None
        if not isinstance(self.data, Mapping):
            return None
        url = self.data.get("resume_gateway_url")
        return url if isinstance(url, str) else None

    @property
    def session_id(self) -> str | None:
        if not (self.is_dispatch and self.event_name == "READY"):
            return None
        if not isinstance(self.data, Mapping):
            return None
        session_id = self.data.get("session_id")
        return session_id if isinstance(session_id, str) else None


def make_heartbeat(sequence: int | None) -> Payload:
    """Heartbeat com a última sequence conhecida — ou ``null`` na primeira.

    O Discord exige o ``d`` presente mesmo quando não há sequence: mandar
    o campo ausente é Decode Error e derruba a conexão.
    """
    return Payload(op=GatewayOpcode.HEARTBEAT, data=sequence)
