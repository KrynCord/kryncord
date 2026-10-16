"""Negociação e decodificação de compressão do Gateway.

Compressão do Gateway existe em dois níveis diferentes, e confundir os
dois é o bug clássico desta área:

* **Transport compression** — vai na *query string* da URL
  (``?compress=zlib-stream``). Usa **um contexto compartilhado**: o
  Discord vai mandando pedaços de um mesmo fluxo comprimido, e só um
  flush marca onde uma mensagem termina e a outra começa.
* **Payload compression** — vai no campo ``compress`` do *Identify*.
  Cada mensagem é um ``zlib`` completo e independente, sem contexto
  entre elas.

Este módulo trata o primeiro. O segundo fica desligado — é o default do
`build_identify`.

**Desligado é o default, e não é preguiça.** Compressão reduz banda, e
banda não é o que derruba um bot: o Gateway entrega tudo igual. O que
comprimir compra é um estado compartilhado que precisa sobreviver a
todo frame, e um estado dessos tem mais formas de ficar errado do que
de ficar certo. Ligar só quando precisar — que é o que a arquitetura
diz com "adicionada quando necessária".

O que está pronto:

``none``
    Padrão. Chega texto, passa adiante.

``zlib-stream``
    Implementado e testado. O contexto é um ``zlib.decompressobj`` que
    vive enquanto a conexão vive — reciclado a cada reconexão, nunca
    entre elas. Um frame só devolve mensagem quando termina no marcador
    de ``Z_SYNC_FLUSH`` (``00 00 ff ff``): antes disso é metade de uma
    mensagem, e devolver metade faria o parser de JSON estourar com um
    erro que não diz nada.

``zstd-stream``
    Recusado com erro explicando o porquê. Exige a biblioteca
    ``zstandard``, que é dependência opcional — ligá-la por trás das
    costas do usuário mudaria o conjunto de dependências do projeto sem
    ninguém ter pedido.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from kryncord.errors import GatewayError

#: Fim de um ``Z_SYNC_FLUSH``. É a única pista confiável de "aqui a
#: mensagem acabou" num fluxo de transporte comprimido.
SYNC_FLUSH = b"\x00\x00\xff\xff"

#: Compressão de transporte. Vai na query string.
TRANSPORT_COMPRESSIONS = ("zlib-stream", "zstd-stream")


class CompressionMode(StrEnum):
    """O que pedimos ao Discord, e o que sabemos decodificar."""

    NONE = "none"
    ZLIB_STREAM = "zlib-stream"
    ZSTD_STREAM = "zstd-stream"

    @property
    def query_value(self) -> str | None:
        """Valor para a query string. `None` = não pedir nada.

        O parâmetro ``compress`` é opcional e **omitido** quando não há
        compressão, não mandado como vazio — o Discord rejeita valor
        desconhecido com um close code que parece bug nosso.
        """
        return None if self is CompressionMode.NONE else str(self)


def build_gateway_url(
    base_url: str,
    *,
    version: int = 10,
    encoding: str = "json",
    compression: CompressionMode = CompressionMode.NONE,
) -> str:
    """Monta a URL de conexão a partir da que o Discord devolveu.

    ``GET /gateway/bot`` devolve só o host (``wss://gateway.discord.gg``).
    A versão e o encoding **têm** que ser mandados explicitamente na
    query: sem eles o Discord assume a versão antiga, e o comportamento
    muda sob os pés.

    A ``resume_gateway_url`` que vem no ``READY`` é uma URL própria, e
    por isso os params são **mesclados** em vez de uma query nova ser
    colada por cima — colar por cima descartaria o que já veio lá.
    """
    if version < 1:
        raise ValueError(f"version precisa ser ao menos 1, recebido {version}")

    parts = urlsplit(base_url)
    if parts.scheme not in ("ws", "wss") or not parts.netloc:
        raise ValueError(f"URL do Gateway inválida (esperado wss://host): {base_url!r}")

    query: dict[str, str] = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["v"] = str(version)
    query["encoding"] = encoding
    query_value = compression.query_value
    if query_value is not None:
        query["compress"] = query_value

    # Host sem caminho vira `/`, que é o que a doc do Discord mostra.
    path = parts.path or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), ""))


class _Decompressor(Protocol):
    """O que este módulo usa de um `zlib.decompressobj()`.

    Existe porque a lib não publica tipo público para o objeto que
    `decompressobj()` devolve — `zlib.Decompress` não está nem em
    runtime nem no typeshed. Declarar o mínimo que usamos resolve sem
    depender de algo que pode sumir.
    """

    def decompress(self, data: bytes) -> bytes: ...


@dataclass(slots=True)
class FrameDecoder:
    """Transforma um frame cru em texto, para `Payload.decode`.

    `decode` devolve `None` quando ainda não tem mensagem completa — só
    em ``zlib-stream``, onde um frame pode ser o começo de uma mensagem.
    Quem chama continua no ``recv()`` até sair texto. No modo ``none``
    nunca devolve `None`: texto é mensagem na hora.
    """

    mode: CompressionMode = CompressionMode.NONE
    _decompressor: _Decompressor | None = field(default=None, init=False, repr=False)
    _pending: bytearray = field(default_factory=bytearray, init=False, repr=False)

    def reset(self) -> None:
        """Descarta o contexto. Chamado a cada nova conexão.

        Manter o ``zlib`` de uma sessão morta na sessão nova faria o
        primeiro frame ser inflado contra um estado que não existe mais —
        sairia lixo, e o parser diria "JSON inválido" sem nunca apontar
        a compressão como suspeita.
        """
        self._decompressor = None
        self._pending.clear()

    def decode(self, data: str | bytes) -> str | None:
        """Devolve um frame completo, ou `None` se ainda faltar pedaço."""
        if self.mode is CompressionMode.ZSTD_STREAM:  # pragma: no cover - já recusado
            raise GatewayError(
                "Compressão `zstd-stream` não é suportada por esta versão da KrynCord."
            )

        if self.mode is CompressionMode.NONE:
            if isinstance(data, bytes):
                return data.decode("utf-8")
            return data

        return self._decode_zlib(data)

    def _decode_zlib(self, data: str | bytes) -> str | None:
        if isinstance(data, str):
            raise GatewayError(
                "Esperava frame binário com `compress=zlib-stream`, "
                f"recebi texto: {data[:80]!r}. Verifique a query da URL."
            )
        if not data:
            return None

        decompressor = self._ensure_decompressor()
        try:
            self._pending.extend(decompressor.decompress(data))
        except zlib.error as exc:
            raise GatewayError(
                f"Falha ao descomprimir frame do Gateway (zlib-stream): {exc}. "
                "O contexto de compressão provavelmente foi reaproveitado entre "
                "conexões — chame `FrameDecoder.reset()` ao reconectar."
            ) from exc

        # Só entrega quando o frame termina em flush. Antes disso é
        # metade de uma mensagem — e meia mensagem é um JSON quebrado,
        # que o parser leria como "JSON inválido" sem nunca apontar a
        # compressão como a suspeita.
        if not data.endswith(SYNC_FLUSH):
            return None

        text = bytes(self._pending).decode("utf-8")
        self._pending.clear()
        return text

    def _ensure_decompressor(self) -> _Decompressor:
        if self._decompressor is None:
            # Window bits 15 = cabeçalho zlib/RFC1950, que é o que o
            # `createInflate` do discord.js usa. `-15` seria deflate cru
            # e daria erro de cabeçalho já no primeiro frame.
            self._decompressor = zlib.decompressobj()
        return self._decompressor


def supports(mode: CompressionMode) -> bool:
    """Esta versão da KrynCord decodifica `mode`?"""
    return mode in (CompressionMode.NONE, CompressionMode.ZLIB_STREAM)
