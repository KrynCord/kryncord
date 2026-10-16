"""Testes de `kryncord.http.authentication` — o token não pode vazar."""

from __future__ import annotations

import pytest

from kryncord.http.authentication import AUTHORIZATION_HEADER, Token, build_auth_header

TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4.GaBcDe.AbCdEfGhIjKlMnOpQrStUvWxYz"


def test_header_value_is_raw_token() -> None:
    """O Discord precisa do valor cru — máscara aqui seria inútil."""
    token = Token(value=TOKEN)
    assert token.header_value == f"Bot {TOKEN}"


def test_repr_masks_the_token() -> None:
    rendered = repr(Token(value=TOKEN))
    assert TOKEN not in rendered
    assert "***" in rendered


def test_str_masks_the_token() -> None:
    rendered = str(Token(value=TOKEN))
    assert TOKEN not in rendered


def test_format_masks_the_token() -> None:
    """f-string cai no __str__ — é o caso que mais vaza em log."""
    token = Token(value=TOKEN)
    rendered = f"conectando com {token}"
    assert TOKEN not in rendered
    assert "***" in rendered


def test_masked_keeps_a_discriminating_tail() -> None:
    """Suficiente para distinguir produção de teste, sem revelar o todo."""
    token = Token(value=TOKEN)
    assert token.masked.endswith(TOKEN[-4:])


def test_short_token_is_fully_masked() -> None:
    """Token com 4 caracteres ou menos: o sufixo seria o token inteiro."""
    assert "***" in str(Token(value="abcd"))
    assert "abcd" not in str(Token(value="abcd"))


def test_empty_token_masks_safely() -> None:
    """Não vira string vazia — vazio em log parece 'sem token' e engana."""
    rendered = str(Token(value=""))
    assert "<vazio>" in rendered
    assert rendered.strip() != ""


def test_custom_prefix_is_preserved_in_header_only() -> None:
    token = Token(value=TOKEN, prefix="Bearer")
    assert token.header_value == f"Bearer {TOKEN}"
    assert "Bearer" in token.masked
    assert TOKEN not in token.masked


def test_dataclass_eq_compares_value_and_prefix() -> None:
    assert Token(value=TOKEN) == Token(value=TOKEN)
    assert Token(value=TOKEN) != Token(value="outro", prefix="Bot")
    assert Token(value=TOKEN) != "não é um token"


def test_dataclass_is_hashable() -> None:
    """Pode ser chave de dict — útil para mapear por credencial."""
    tokens = {Token(value=TOKEN): "principal"}
    assert tokens[Token(value=TOKEN)] == "principal"


# --------------------------------------------------------------------------
# build_auth_header
# --------------------------------------------------------------------------


def test_build_auth_header_returns_authorization() -> None:
    headers = build_auth_header(Token(value=TOKEN))
    assert headers[AUTHORIZATION_HEADER] == f"Bot {TOKEN}"


def test_build_auth_header_with_none_returns_empty() -> None:
    """Não `Authorization: None` — ausência total do header."""
    assert build_auth_header(None) == {}


def test_headers_built_do_not_leak_in_repr() -> None:
    """O dict de headers é normalmente logado inteiro — o token estará lá,
    porque é obrigatório. O que não pode é aparecer quando NÃO é
    obrigatório."""
    assert AUTHORIZATION_HEADER not in build_auth_header(None)


@pytest.mark.parametrize("prefix", ["Bot", "Bearer"])
def test_every_prefix_masks(prefix: str) -> None:
    token = Token(value=TOKEN, prefix=prefix)
    assert TOKEN not in repr(token)
    assert TOKEN not in str(token)
