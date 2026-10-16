"""Codificação ``multipart/form-data`` para uploads.

O Discord recebe anexos num corpo multipart: o JSON do payload em um campo
``payload_json``, e cada arquivo em ``files[0]``, ``files[1]``... Este
módulo monta esse corpo.

Duas coisas aqui parecem detalhe e não são:

**A fronteira não pode aparecer no conteúdo.** Se ``--abc123`` existir
dentro de um arquivo enviado, o Discord lê o arquivo até ali e corta — e
o erro que vem depois é genérico, do tipo "invalid asset". Por isso a
fronteira é aleatória e é *verificada* contra cada parte, não assumida.

**O fim importa.** O corpo termina com ``--fronteira--`` seguido de CRLF.
Esquecer a CRLF final faz o Discord aceitar o upload e descartar o
último arquivo — silenciosamente, num request que parece ter dado certo.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

#: Fronteira com prefixo reconhecível: num log de requisição, dá para ver
#: que o corpo é nosso e não de um proxy que reescreveu o request.
BOUNDARY_PREFIX = "----------KrynCordBoundary"

#: Quantos bytes hexadecimais na fronteira. 16 bytes = 128 bits — colidir
#: com o conteúdo de um arquivo por acaso é mais improvável que acertar a
#: loteria várias vezes seguidas.
BOUNDARY_ENTROPY_BYTES = 16

#: Tentativas antes de desistir de achar uma fronteira livre. Com 128 bits
#: de entropia a segunda tentativa já é desnecessária; o laço existe
#: porque "nunca" não é garantia, é esperança.
MAX_BOUNDARY_ATTEMPTS = 8

#: Fim de linha obrigatório do RFC 7578. Só LF não vale.
CRLF = b"\r\n"

OCTET_STREAM = "application/octet-stream"


class MultipartError(ValueError):
    """Falha ao montar o corpo multipart."""


@dataclass(frozen=True, slots=True)
class FilePart:
    """Um arquivo a ser enviado como ``files[n]``.

    A descrição do attachment **não** mora aqui: o Discord lê
    ``attachments[n].description`` do ``payload_json``, não de um header
    do multipart. Colocá-la aqui seria inventar um campo que ninguém lê.
    """

    field: str
    "``files[0]``, ``files[1]``... O índice importa: é como o Discord casa\ncada arquivo com o attachment correspondente no `payload_json`."

    filename: str
    content: bytes
    content_type: str = OCTET_STREAM

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass(frozen=True, slots=True)
class Multipart:
    """Corpo pronto, e o header que descreve."""

    body: bytes
    content_type: str

    @property
    def boundary(self) -> str:
        """Fronteira, extraída do ``content-type``."""
        _, _, value = self.content_type.partition("boundary=")
        return value


def generate_boundary(*, parts: Sequence[FilePart] = ()) -> str:
    """Fronteira aleatória que não ocorre em nenhuma das partes.

    Não basta ser aleatória: tem que ser *verificadamente* ausente do
    conteúdo. Um arquivo que por azar contenha a fronteira seria cortado
    no meio — e o Discord reportaria "invalid asset" sem dizer por quê.
    """
    for _ in range(MAX_BOUNDARY_ATTEMPTS):
        candidate = f"{BOUNDARY_PREFIX}{secrets.token_hex(BOUNDARY_ENTROPY_BYTES)}"
        if not _collides(candidate, None, parts):
            return candidate
    raise MultipartError(
        f"Não foi possível achar uma fronteira livre em {MAX_BOUNDARY_ATTEMPTS} tentativas. "
        "Isso só acontece se o conteúdo for construído para colidir."
    )


def encode(
    *,
    fields: Mapping[str, str] | None = None,
    files: Sequence[FilePart] = (),
    boundary: str | None = None,
) -> Multipart:
    """Monta o corpo multipart e devolve ``(corpo, content-type)``.

    `fields` vira campos de texto simples; `files` vira partes com
    conteúdo binário. A ordem é preservada: campos primeiro, depois
    arquivos — é a ordem que os exemplos oficiais usam.
    """
    if boundary is None:
        boundary = generate_boundary(parts=files)
    elif _collides(boundary, fields, files):
        raise MultipartError(
            f"A fronteira fornecida ocorre dentro do conteúdo: {boundary!r}. "
            "O corpo ficaria truncado na primeira ocorrência. "
            "Deixe generate_boundary() escolher."
        )

    chunks = _chunks(fields or {}, files, boundary.encode())
    return Multipart(
        body=b"".join(chunks),
        content_type=f"multipart/form-data; boundary={boundary}",
    )


def encode_payload_json(payload_json: str, files: Sequence[FilePart]) -> Multipart:
    """Atalho do caso de uso real: JSON do Discord + anexos.

    É assim que um ``POST /channels/:id/messages`` com arquivo sai: o
    objeto da mensagem inteiro em ``payload_json``, e cada arquivo em
    ``files[n]``.
    """
    return encode(fields={"payload_json": payload_json}, files=files)


def total_size(parts: Sequence[FilePart]) -> int:
    """Soma dos arquivos, sem contar o overhead do multipart.

    Útil para recusar cedo: o Discord responde 413 só depois de receber
    tudo, e 25 MB jogados fora são 25 MB de banda e de espera.
    """
    return sum(part.size for part in parts)


def _chunks(fields: Mapping[str, str], files: Sequence[FilePart], boundary: bytes) -> list[bytes]:
    chunks: list[bytes] = []

    for name, value in fields.items():
        chunks.append(b"--" + boundary + CRLF)
        chunks.append(_header(f'Content-Disposition: form-data; name="{_escape(name)}"'))
        chunks.append(CRLF)
        chunks.append(value.encode("utf-8") + CRLF)

    for part in files:
        disposition = (
            f'Content-Disposition: form-data; name="{_escape(part.field)}"; '
            f'filename="{_escape(part.filename)}"'
        )
        chunks.append(b"--" + boundary + CRLF)
        chunks.append(_header(disposition))
        chunks.append(_header("Content-Type: " + part.content_type))
        chunks.append(CRLF)
        chunks.append(part.content + CRLF)

    # O fecho tem que ser exatamente `--fronteira--` + CRLF. Uma CRLF
    # faltando faz o Discord aceitar e descartar o último arquivo.
    chunks.append(b"--" + boundary + b"--" + CRLF)
    return chunks


def _header(line: str) -> bytes:
    return line.encode("utf-8") + CRLF


def _escape(value: str) -> str:
    """Escapa ``"`` e ``\\`` para o valor sobreviver como quoted-string.

    Sem isto, um nome de arquivo com aspas fecha o atributo no meio e
    descaracteriza o restante do header.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _collides(boundary: str, fields: Mapping[str, str] | None, files: Sequence[FilePart]) -> bool:
    needle = boundary.encode()
    if any(needle in value.encode("utf-8") for value in (fields or {}).values()):
        return True
    return any(needle in part.content for part in files)
