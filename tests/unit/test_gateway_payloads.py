"""Testes de `kryncord.gateway.payloads` — o parser do protocolo.

O alvo aqui são as armadilhas que a validação existe para pegar: ``op``
que chega como ``bool``, ``s`` que chega como string, ``t`` que existe
fora de dispatch. Cada uma delas, se passar, vira um bug num lugar que
não tem nada a ver com o lugar onde o frame entrou.
"""

from __future__ import annotations

import json

import pytest

from kryncord.enums import GatewayOpcode
from kryncord.errors import GatewayError
from kryncord.gateway.payloads import Payload, make_heartbeat

# --------------------------------------------------------------------------
# Decodificação
# --------------------------------------------------------------------------


def test_decode_dispatch_full_frame() -> None:
    raw = json.dumps(
        {
            "op": 0,
            "d": {"content": "oi"},
            "s": 42,
            "t": "MESSAGE_CREATE",
        }
    )
    payload = Payload.decode(raw)

    assert payload.op == GatewayOpcode.DISPATCH
    assert payload.data == {"content": "oi"}
    assert payload.sequence == 42
    assert payload.event_name == "MESSAGE_CREATE"
    assert payload.is_dispatch is True


def test_decode_accepts_bytes_frame() -> None:
    """O transporte chega como `bytes` no modo sem compressão às vezes."""
    payload = Payload.decode(b'{"op":10,"d":{"heartbeat_interval":41250}}')
    assert payload.is_hello is True


def test_heartbeat_omitted_t_normalizes_to_none() -> None:
    """O Discord manda `t: null` em heartbeat; omitir também é válido."""
    payload = Payload.decode('{"op":1,"d":null,"s":null,"t":null}')
    assert payload.event_name is None
    assert payload.sequence is None


@pytest.mark.parametrize("raw", ["não é json", "[1,2,3]", '"uma string"', "42"])
def test_decode_rejects_non_object(raw: str) -> None:
    """JSON válido que não é objeto também é frame inválido."""
    with pytest.raises(GatewayError):
        Payload.decode(raw)


def test_decode_rejects_binary_frame() -> None:
    with pytest.raises(GatewayError):
        Payload.decode(b"\x00\x01\x02\x03")


@pytest.mark.parametrize(
    "body",
    [
        {"op": True},
        {"op": "10"},
        {"op": 10.5},
        {"op": None},
        {},
    ],
)
def test_op_must_be_int_and_not_bool(body: dict[str, object]) -> None:
    """``{"op": true}`` viraria Heartbeat — `bool` é subclasse de `int`."""
    with pytest.raises(GatewayError, match="`op`"):
        Payload.decode(json.dumps(body))


def test_sequence_must_be_int_or_null() -> None:
    with pytest.raises(GatewayError, match="`s`"):
        Payload.decode('{"op":0,"d":null,"s":"42","t":"X"}')


def test_sequence_must_not_be_bool() -> None:
    with pytest.raises(GatewayError, match="`s`"):
        Payload.decode('{"op":0,"d":null,"s":true,"t":"X"}')


def test_event_name_must_be_string_or_null() -> None:
    with pytest.raises(GatewayError, match="`t`"):
        Payload.decode('{"op":0,"d":null,"s":1,"t":7}')


# --------------------------------------------------------------------------
# Serialização
# --------------------------------------------------------------------------


def test_encode_omits_null_fields() -> None:
    """Campos nulos saem, como o Discord espera no envio."""
    encoded = Payload(op=GatewayOpcode.HEARTBEAT, data=None).encode()
    assert encoded == '{"op":1,"d":null}'


def test_encode_keeps_unicode_readable() -> None:
    encoded = Payload(op=0, data={"content": "olá"}, sequence=1, event_name="X").encode()
    assert "olá" in encoded


def test_encode_decode_round_trip() -> None:
    original = Payload(op=0, data={"a": 1}, sequence=9, event_name="READY")
    assert Payload.decode(original.encode()) == original


# --------------------------------------------------------------------------
# Predicados
# --------------------------------------------------------------------------


def test_predicates_are_true_only_for_their_opcode() -> None:
    checks = [
        (GatewayOpcode.DISPATCH, "is_dispatch"),
        (GatewayOpcode.HELLO, "is_hello"),
        (GatewayOpcode.HEARTBEAT, "is_heartbeat"),
        (GatewayOpcode.HEARTBEAT_ACK, "is_heartbeat_ack"),
        (GatewayOpcode.RECONNECT, "is_reconnect"),
        (GatewayOpcode.INVALID_SESSION, "is_invalid_session"),
    ]
    for opcode, name in checks:
        payload = Payload(op=opcode)
        assert getattr(payload, name) is True, f"{name} deveria ser True em op {opcode}"
        others = [other for other, _ in checks if other != opcode]
        for other in others:
            assert getattr(Payload(op=other), name) is False


def test_is_resumable_is_none_outside_invalid_session() -> None:
    """`None` e não `False`: `False` diria "o Discord disse que não dá"."""
    assert Payload(op=GatewayOpcode.HELLO).is_resumable is None
    assert Payload(op=GatewayOpcode.INVALID_SESSION, data=True).is_resumable is True
    assert Payload(op=GatewayOpcode.INVALID_SESSION, data=False).is_resumable is False
    # Corpo que não é bool é tratado como "não dá para retomar".
    assert Payload(op=GatewayOpcode.INVALID_SESSION, data={}).is_resumable is False


def test_heartbeat_interval_only_from_hello() -> None:
    assert Payload(op=GatewayOpcode.DISPATCH).heartbeat_interval_ms is None
    hello = Payload(op=GatewayOpcode.HELLO, data={"heartbeat_interval": 41250})
    assert hello.heartbeat_interval_ms == 41250.0


def test_heartbeat_interval_rejects_bool_and_garbage() -> None:
    assert (
        Payload(op=GatewayOpcode.HELLO, data={"heartbeat_interval": True}).heartbeat_interval_ms
        is None
    )
    assert (
        Payload(op=GatewayOpcode.HELLO, data={"heartbeat_interval": "41250"}).heartbeat_interval_ms
        is None
    )
    assert Payload(op=GatewayOpcode.HELLO, data=None).heartbeat_interval_ms is None


def test_ready_accessors_only_apply_to_ready_dispatch() -> None:
    other = Payload(op=0, data={"session_id": "abc"}, sequence=1, event_name="RESUMED")
    assert other.resume_gateway_url is None
    assert other.session_id is None

    ready = Payload(
        op=0,
        data={"session_id": "abc", "resume_gateway_url": "wss://x.discord.gg"},
        sequence=1,
        event_name="READY",
    )
    assert ready.session_id == "abc"
    assert ready.resume_gateway_url == "wss://x.discord.gg"


def test_ready_accessors_tolerate_non_mapping_body() -> None:
    ready = Payload(op=0, data="lixo", sequence=1, event_name="READY")
    assert ready.session_id is None
    assert ready.resume_gateway_url is None


# --------------------------------------------------------------------------
# make_heartbeat
# --------------------------------------------------------------------------


def test_make_heartbeat_carries_sequence() -> None:
    beat = make_heartbeat(42)
    assert beat.op == GatewayOpcode.HEARTBEAT
    assert beat.data == 42
    assert '"s"' not in beat.encode()


def test_first_heartbeat_has_explicit_null() -> None:
    """O Discord exige o `d` presente mesmo sem sequence — `null`, não ausente."""
    beat = make_heartbeat(None)
    assert beat.encode() == '{"op":1,"d":null}'
