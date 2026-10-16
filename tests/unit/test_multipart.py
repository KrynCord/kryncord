"""Testes de `kryncord.http.multipart` — o corpo do upload.

O multipart é a parte do HTTP que falha **silenciosamente**: o request
dá 200 e o Discord descarta o último arquivo, ou corta o meio de um
anexo e responde "invalid asset" sem dizer onde. Por isso os testes aqui
olham o corpo byte a byte em vez de conferir que "algo foi montado".
"""

from __future__ import annotations

import pytest

from kryncord.http.multipart import (
    BOUNDARY_PREFIX,
    CRLF,
    MAX_BOUNDARY_ATTEMPTS,
    FilePart,
    Multipart,
    MultipartError,
    encode,
    encode_payload_json,
    generate_boundary,
    total_size,
)

BOUNDARY = f"{BOUNDARY_PREFIX}prova"


def _file(name: str = "arquivo.txt", content: bytes = b"conteudo", **kwargs: object) -> FilePart:
    return FilePart(field="files[0]", filename=name, content=content, **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Estrutura do corpo
# --------------------------------------------------------------------------


def test_fields_come_before_files() -> None:
    """É a ordem que os exemplos oficiais usam, e alguns clientes leem."""
    result = encode(fields={"content": "olá"}, files=[_file()], boundary=BOUNDARY)

    assert result.body.index(b'name="content"') < result.body.index(b'name="files[0]"')


def test_body_starts_and_ends_correctly() -> None:
    result = encode(fields={"content": "oi"}, boundary=BOUNDARY)

    assert result.body.startswith(b"--" + BOUNDARY.encode() + CRLF)
    assert result.body.endswith(b"--" + BOUNDARY.encode() + b"--" + CRLF)


def test_closing_crlf_is_present() -> None:
    """Sem esta CRLF o Discord aceita o upload e descarta o último
    arquivo — silenciosamente, num request que parece ter dado certo."""
    result = encode(files=[_file()], boundary=BOUNDARY)
    assert result.body.endswith(CRLF)


def test_file_part_has_content_type_and_bytes() -> None:
    result = encode(files=[_file(content_type="image/png")], boundary=BOUNDARY)

    assert b"Content-Type: image/png" in result.body
    assert b"conteudo" in result.body


def test_content_type_header_carries_the_boundary() -> None:
    result = encode(boundary=BOUNDARY)
    assert result.content_type == f"multipart/form-data; boundary={BOUNDARY}"


def test_boundary_round_trips_through_content_type() -> None:
    """O `requests`/`httpx` lê a fronteira do header, não de uma
    variável. Se os dois divergirem, o corpo vira lixo."""
    result = encode(files=[_file()])
    assert result.body.startswith(b"--" + result.boundary.encode() + CRLF)
    assert b"--" + result.boundary.encode() + b"--" in result.body


def test_empty_encode_is_a_valid_closed_body() -> None:
    result = encode(boundary=BOUNDARY)
    assert result.body == b"--" + BOUNDARY.encode() + b"--" + CRLF


# --------------------------------------------------------------------------
# Fronteira
# --------------------------------------------------------------------------


def test_generated_boundary_is_unique_and_prefixed() -> None:
    first, second = generate_boundary(), generate_boundary()

    assert first != second
    assert first.startswith(BOUNDARY_PREFIX)
    assert second.startswith(BOUNDARY_PREFIX)


def test_generated_boundary_skips_a_collision_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Não basta ser aleatória: tem que ser *verificadamente* ausente.

    Um arquivo que por azar contenha a fronteira seria cortado no meio —
    e o Discord reportaria "invalid asset" sem dizer por quê.

    Aqui o `token_hex` é forçado a devolver o mesmo valor duas vezes, e
    um livre na terceira: sem o laço de `MAX_BOUNDARY_ATTEMPTS`, a
    segunda tentativa nem existiria.
    """
    attempts = iter(["aaaa", "aaaa", "bbbb"])
    monkeypatch.setattr("kryncord.http.multipart.secrets.token_hex", lambda n: next(attempts))

    # O valor colidente está dentro do arquivo, de propósito.
    colliding = f"{BOUNDARY_PREFIX}aaaa".encode()
    boundary = generate_boundary(
        parts=[FilePart(field="files[0]", filename="f", content=b"prefixo " + colliding)]
    )

    assert boundary == f"{BOUNDARY_PREFIX}bbbb"


def test_colliding_boundary_is_rejected_not_silently_replaced() -> None:
    """Trocar em silêncio esconderia o problema — e a próxima chamada
    poderia colidir de novo no lugar que ninguém olha."""
    with pytest.raises(MultipartError, match="ocorre dentro do conteúdo"):
        encode(files=[_file(content=f"x{BOUNDARY}y".encode())], boundary=BOUNDARY)


def test_colliding_boundary_in_a_field_is_also_rejected() -> None:
    with pytest.raises(MultipartError, match="ocorre dentro do conteúdo"):
        encode(fields={"content": BOUNDARY}, boundary=BOUNDARY)


def test_max_attempts_is_a_sane_number() -> None:
    """Com 128 bits de entropia a segunda tentativa já é desnecessária.

    O laço existe porque "nunca" não é garantia, é esperança.
    """
    assert MAX_BOUNDARY_ATTEMPTS >= 2


# --------------------------------------------------------------------------
# Escapes
# --------------------------------------------------------------------------


def test_quotes_in_filename_are_escaped() -> None:
    """Sem escape, a aspas fecha o atributo no meio e descaracteriza o
    resto do header."""
    result = encode(files=[_file(name='meu"arquivo.txt')], boundary=BOUNDARY)
    assert b'filename="meu\\"arquivo.txt"' in result.body


def test_backslashes_in_filename_are_escaped() -> None:
    result = encode(files=[_file(name="caminho\\arquivo.txt")], boundary=BOUNDARY)
    assert b'filename="caminho\\\\arquivo.txt"' in result.body


def test_quotes_in_field_name_are_escaped() -> None:
    result = encode(
        files=[FilePart(field='files[0]"x', filename="f", content=b"")], boundary=BOUNDARY
    )
    assert b'name="files[0]\\"x"' in result.body


def test_unicode_survives_utf8() -> None:
    result = encode(files=[_file(name="café.txt", content="olá".encode())], boundary=BOUNDARY)
    assert "café.txt".encode() in result.body


# --------------------------------------------------------------------------
# encode_payload_json — o atalho do caso real
# --------------------------------------------------------------------------


def test_payload_json_field_is_first_and_carries_the_body() -> None:
    """É assim que um ``POST /channels/:id/messages`` com arquivo sai."""
    payload = '{"content":"veja","attachments":[{"id":0,"filename":"a.txt"}]}'
    result = encode_payload_json(payload, [_file()])

    assert b'name="payload_json"' in result.body
    assert payload.encode() in result.body
    assert result.body.index(b'name="payload_json"') < result.body.index(b'name="files[0]"')


def test_payload_json_without_files_is_still_valid() -> None:
    result = encode_payload_json('{"content":"oi"}', [])
    assert b'{"content":"oi"}' in result.body


# --------------------------------------------------------------------------
# total_size
# --------------------------------------------------------------------------


def test_total_size_sums_only_the_files() -> None:
    """Útil para recusar cedo: o Discord responde 413 só depois de
    receber tudo, e 25 MB jogados fora são 25 MB de banda e de espera."""
    parts = [
        FilePart(field="files[0]", filename="a", content=b"12345"),
        FilePart(field="files[1]", filename="b", content=b"678"),
    ]
    assert total_size(parts) == 8


def test_total_size_of_nothing_is_zero() -> None:
    assert total_size([]) == 0


def test_file_part_size_is_the_content_length() -> None:
    assert _file(content=b"abcdefgh").size == 8


# --------------------------------------------------------------------------
# Multipart
# --------------------------------------------------------------------------


def test_multipart_is_a_plain_data_holder() -> None:
    body = b"--x--\r\n"
    result = Multipart(body=body, content_type="multipart/form-data; boundary=x")
    assert result.body == body
