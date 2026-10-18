"""Testes de `kryncord.gateway.compression` — URL e decodificação.

Dois assuntos que não se misturam, e os testes existem para mantê-los
separados: a **URL** (onde se pede a compressão) e o **frame** (onde ela
é desfeita). Pedir na query errada é o erro que o Discord responde com
um close code aparentemente sem relação com compressão.
"""

from __future__ import annotations

import sys
import zlib

import pytest

from kryncord.errors import GatewayError
from kryncord.gateway.compression import (
    SYNC_FLUSH,
    ZSTD_INSTALADO,
    CompressionMode,
    FrameDecoder,
    build_gateway_url,
    supports,
)


def _compress_stream(*messages: str) -> bytes:
    """Comprime várias mensagens como o Discord: um fluxo, um flush por
    mensagem."""
    compressor = zlib.compressobj()
    out = b""
    for message in messages:
        out += compressor.compress(message.encode())
        out += compressor.flush(zlib.Z_SYNC_FLUSH)
    return out


# --------------------------------------------------------------------------
# build_gateway_url
# --------------------------------------------------------------------------


def test_url_carries_version_and_encoding() -> None:
    url = build_gateway_url("wss://gateway.discord.gg")
    assert url == "wss://gateway.discord.gg/?v=10&encoding=json"


def test_compression_param_is_omitted_when_none() -> None:
    """O Discord rejeita valor desconhecido com um close code que parece
    bug nosso — por isso omite, não manda vazio."""
    url = build_gateway_url("wss://gateway.discord.gg")
    assert "compress" not in url


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (CompressionMode.ZLIB_STREAM, "compress=zlib-stream"),
        (CompressionMode.ZSTD_STREAM, "compress=zstd-stream"),
    ],
)
def test_compression_param_when_requested(mode: CompressionMode, expected: str) -> None:
    assert expected in build_gateway_url("wss://gateway.discord.gg", compression=mode)


def test_existing_query_params_are_merged_not_replaced() -> None:
    """A `resume_gateway_url` vem com a query própria dela.

    Colar uma query nova por cima descartaria o que já veio lá.
    """
    url = build_gateway_url("wss://us-east.discord.gg?trace_id=abc")
    assert "trace_id=abc" in url
    assert "v=10" in url
    assert "encoding=json" in url


def test_resume_url_keeps_its_host() -> None:
    url = build_gateway_url("wss://bogus-b.discord.gg", version=9, encoding="etf")
    assert url.startswith("wss://bogus-b.discord.gg/")
    assert "v=9" in url
    assert "encoding=etf" in url


def test_empty_path_becomes_slash() -> None:
    """A doc do Discord mostra o host terminando em `/`."""
    assert build_gateway_url("wss://gateway.discord.gg").endswith("/?v=10&encoding=json")


@pytest.mark.parametrize("url", ["", "sem-esquema", "https://ok/mas-nao-wss"])
def test_invalid_base_url_is_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="inválida"):
        build_gateway_url(url)


def test_version_must_be_positive() -> None:
    with pytest.raises(ValueError, match="version"):
        build_gateway_url("wss://gateway.discord.gg", version=0)


# --------------------------------------------------------------------------
# FrameDecoder — modo none
# --------------------------------------------------------------------------


def test_none_mode_passes_text_through() -> None:
    decoder = FrameDecoder(CompressionMode.NONE)
    assert decoder.decode('{"op":10}') == '{"op":10}'


def test_none_mode_decodes_bytes_to_text() -> None:
    """Bytes chegam quando o transporte entrega binário mesmo sem pedir."""
    decoder = FrameDecoder(CompressionMode.NONE)
    assert decoder.decode(b'{"op":10}') == '{"op":10}'


# --------------------------------------------------------------------------
# FrameDecoder — zlib-stream
# --------------------------------------------------------------------------


def test_zlib_stream_decodes_a_single_message() -> None:
    decoder = FrameDecoder(CompressionMode.ZLIB_STREAM)
    frame = _compress_stream('{"op":10,"d":{"heartbeat_interval":41250}}')

    assert decoder.decode(frame) == '{"op":10,"d":{"heartbeat_interval":41250}}'


def test_zlib_stream_keeps_context_between_frames() -> None:
    """O contexto vive enquanto a conexão vive — é o que torna o modo
    "stream" e não "frames independentes".

    As duas mensagens saem do **mesmo** compressor, e o corte é exatamente
    no fim do flush da primeira — que é como o Discord faz: cada evento
    sai com o seu ``Z_SYNC_FLUSH``.
    """
    decoder = FrameDecoder(CompressionMode.ZLIB_STREAM)
    compressor = zlib.compressobj()

    first = compressor.compress(b'{"op":0,"s":1,"t":"A"}')
    first += compressor.flush(zlib.Z_SYNC_FLUSH)
    second = compressor.compress(b'{"op":0,"s":2,"t":"B"}')
    second += compressor.flush(zlib.Z_SYNC_FLUSH)

    assert decoder.decode(first) == '{"op":0,"s":1,"t":"A"}'
    # Sem novo `decompressobj()`: a segunda metade só fecha com o estado
    # da primeira.
    assert decoder.decode(second) == '{"op":0,"s":2,"t":"B"}'


def test_zlib_stream_waits_for_the_flush_marker() -> None:
    """Frame sem o marcador devolve `None` — meia mensagem é JSON quebrado.

    O corte é no meio dos **dados**, antes do ``Z_SYNC_FLUSH``: é o que
    um socket entrega quando a mensagem ainda não terminou.
    """
    decoder = FrameDecoder(CompressionMode.ZLIB_STREAM)
    stream = _compress_stream('{"op":0,"s":1,"t":"A"}')

    head, tail = stream[: -len(SYNC_FLUSH)], stream[-len(SYNC_FLUSH) :]

    assert decoder.decode(head) is None
    assert decoder.decode(tail) == '{"op":0,"s":1,"t":"A"}'


def _split_at_flush(stream: bytes) -> tuple[bytes, bytes]:
    """Corta logo após o primeiro ``Z_SYNC_FLUSH`` — que é exatamente
    onde o Discord termina um frame."""
    boundary = stream.index(SYNC_FLUSH) + len(SYNC_FLUSH)
    return stream[:boundary], stream[boundary:]


def test_two_messages_come_out_as_two_frames() -> None:
    """Uma mensagem por marcador.

    Entregar as duas juntas seria um JSON colado no outro, que o parser
    leria como frame inválido.
    """
    decoder = FrameDecoder(CompressionMode.ZLIB_STREAM)
    stream = _compress_stream('{"op":0,"s":1,"t":"A"}', '{"op":0,"s":2,"t":"B"}')
    first, second = _split_at_flush(stream)

    assert decoder.decode(first) == '{"op":0,"s":1,"t":"A"}'
    assert decoder.decode(second) == '{"op":0,"s":2,"t":"B"}'


def test_zlib_stream_rejects_text_frames() -> None:
    """Pedido `compress=zlib-stream` e o Discord manda texto = a query
    não foi aceita. Dizer isso é mais útil que um JSON inválido."""
    decoder = FrameDecoder(CompressionMode.ZLIB_STREAM)
    with pytest.raises(GatewayError, match="compress=zlib-stream"):
        decoder.decode('{"op":10}')


def test_empty_frame_yields_none_not_a_crash() -> None:
    decoder = FrameDecoder(CompressionMode.ZLIB_STREAM)
    assert decoder.decode(b"") is None


def test_reset_starts_a_fresh_context() -> None:
    """`reset()` roda a cada reconexão.

    Sem ele, o `zlib` da sessão morta ficaria inflando a sessão nova
    contra um estado que não existe mais — sairia lixo, e o parser
    diria "JSON inválido" sem nunca apontar a compressão como suspeita.
    """
    decoder = FrameDecoder(CompressionMode.ZLIB_STREAM)
    stream = _compress_stream('{"op":0,"s":1,"t":"A"}', '{"op":0,"s":2,"t":"B"}')
    first, _ = _split_at_flush(stream)

    decoder.decode(first)
    decoder.reset()

    # Socket novo = fluxo novo, com o próprio cabeçalho zlib.
    fresh = _compress_stream('{"op":0,"s":9,"t":"Z"}')
    assert decoder.decode(fresh) == '{"op":0,"s":9,"t":"Z"}'


def test_reset_refuses_a_stale_half_message() -> None:
    """Metade de mensagem da sessão morta não completa nada da nova.

    O zlib recusa sem cabeçalho, e o erro que sai daqui aponta a
    compressão como suspeita — que é o que o texto do `GatewayError`
    promete.
    """
    decoder = FrameDecoder(CompressionMode.ZLIB_STREAM)
    stream = _compress_stream('{"op":0,"s":1,"t":"A"}', '{"op":0,"s":2,"t":"B"}')
    first, second = _split_at_flush(stream)

    decoder.decode(first)
    decoder.reset()

    with pytest.raises(GatewayError, match="descomprimir"):
        decoder.decode(second)


def test_sync_flush_marker_is_the_zlib_one() -> None:
    """O marcador é o que a lib escreve ao dar flush — se mudar de
    lugar, o decoder entrega metade de mensagem."""
    assert SYNC_FLUSH == b"\x00\x00\xff\xff"
    assert _compress_stream("x").endswith(SYNC_FLUSH)


def test_zstd_sem_biblioteca_erro_acionavel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem o extra, o pedido de zstd falha na cara e diz o comando.

    O monkeypatch zera o import em qualquer ambiente — mesmo onde o
    `zstandard` está instalado, o teste prova o caminho do usuário sem
    o `kryncord[zstd]`.
    """
    monkeypatch.setitem(sys.modules, "zstandard", None)

    decoder = FrameDecoder(CompressionMode.ZSTD_STREAM)
    with pytest.raises(GatewayError, match=r"kryncord\[zstd\]"):
        decoder.decode(b"frame comprimido de mentira")


def test_zstd_roundtrip() -> None:
    """Um frame zstd completo descompressa no texto original.

    `importorskip` de propósito: a suíte inteira tem que continuar
    verde no ambiente **sem** o extra (regras §16) — aqui o teste pula,
    e o `test_zstd_sem_biblioteca_erro_acionavel` cobre o caminho sem a
    lib.
    """
    zstandard = pytest.importorskip("zstandard")
    texto = '{"op": 0, "t": "READY", "s": 1, "d": {"session_id": "abc"}}'

    decoder = FrameDecoder(CompressionMode.ZSTD_STREAM)
    assert decoder.decode(zstandard.ZstdCompressor().compress(texto.encode())) == texto


def test_zstd_reset_e_noop_sem_estado_entre_frames() -> None:
    """Contexto por frame: `reset()` não tem o que limpar, e o segundo
    frame continua descompressando direito."""
    zstandard = pytest.importorskip("zstandard")
    compressor = zstandard.ZstdCompressor()
    decoder = FrameDecoder(CompressionMode.ZSTD_STREAM)

    primeiro = decoder.decode(compressor.compress(b'{"n": 1}'))
    decoder.reset()
    segundo = decoder.decode(compressor.compress(b'{"n": 2}'))

    assert primeiro == '{"n": 1}'
    assert segundo == '{"n": 2}'


def test_supports_reports_only_what_we_decode() -> None:
    assert supports(CompressionMode.NONE) is True
    assert supports(CompressionMode.ZLIB_STREAM) is True
    # zstd depende do extra — a resposta é a presença do `zstandard`,
    # não uma decisão fixa do código.
    assert supports(CompressionMode.ZSTD_STREAM) is ZSTD_INSTALADO
