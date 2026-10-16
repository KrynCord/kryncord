"""Cores — nome, hex, inteiro e a sorte de `random_color()`.

A tabela de nomes é a paleta do Discord (a que o `discord-api-types`
chama de `Colors`), porque é a única que não é invenção de biblioteca:
`"Blurple"` significa a mesma coisa para quem vem do discord.js e para
quem lê o portal do Discord.

`"Random"` **não** é parseável de propósito (E4): cor aleatória na
classe `Embed` faria o **mesmo** embed renderizar diferente a cada
construção — quem quer sorte pede, com `random_color()` ou
`create_embed(color="Random")`.
"""

from __future__ import annotations

import random
from enum import IntEnum

from kryncord.errors import ComponentError


class AccentColor(IntEnum):
    """A paleta nomeada — aceita como cor de `Container` e `Embed`."""

    DEFAULT = 0x000000
    WHITE = 0xFFFFFF
    AQUA = 0x1ABC9C
    GREEN = 0x57F287
    BLUE = 0x3498DB
    YELLOW = 0xFEE75C
    PURPLE = 0x9B59B6
    FUCHSIA = 0xEB459E
    RED = 0xED4245
    GREY = 0x99AAB5
    DARK_GREY = 0x2C2F33
    NOT_QUITE_BLACK = 0x23272A
    BLURPLE = 0x5865F2


#: Nome aceito → inteiro. Chaves minúsculas porque o usuário escreve
#: `"Blurple"` e `"blurple"` com a mesma intenção — e a mensagem de erro
#: lista o que é aceito, então o conjunto tem um dono só.
_NOMES: dict[str, int] = {c.name.lower(): int(c) for c in AccentColor}


def parse_color(cor: str | int | AccentColor) -> int:
    """Qualquer forma aceita → inteiro RGB.

    - `"#5865F2"` / `"5865F2"` → hex
    - `"Blurple"` / `"green"` → tabela de nomes
    - `0x5865F2` / `5793266` / `AccentColor.GREEN` → passa

    Fora da tabela é `ComponentError` com a lista — cor inválida
    descoberta no render é um embed invisível, e não um erro.
    """
    if isinstance(cor, AccentColor):
        return int(cor)
    if isinstance(cor, int):
        return _inteiro(cor)
    if isinstance(cor, str):
        texto = cor.strip()
        if texto.startswith("#"):
            return _hexadecimal(texto[1:], cor)
        if texto.lower() in _NOMES:
            return _NOMES[texto.lower()]
        if _e_hexadecimal(texto):
            return _hexadecimal(texto, cor)
        raise ComponentError(
            f"cor {cor!r} não existe — nomes aceitos: {sorted(_NOMES)}, ou hex '#5865F2'"
        )
    raise ComponentError(f"cor precisa ser str | int | AccentColor, veio {type(cor).__name__}")


def _inteiro(valor: int) -> int:
    if not 0 <= valor <= 0xFFFFFF:
        raise ComponentError(f"cor {valor} fora da faixa 0..16777215 — RGB tem 24 bits")
    return valor


def _e_hexadecimal(texto: str) -> bool:
    return len(texto) == 6 and all(c in "0123456789abcdefABCDEF" for c in texto)


def _hexadecimal(texto: str, original: object) -> int:
    try:
        return int(texto, 16)
    except ValueError:
        raise ComponentError(f"cor {original!r} não é hex válido") from None


def random_color() -> int:
    """Uma cor qualquer, sempre nova — para `create_embed(color="Random")`.

    Função pura de sorte explícita (E4): quem a chama **vê** que o
    resultado muda; `"Random"` na classe seria o embed que renderiza
    diferente a cada boot sem ninguém ter pedido.
    """
    return random.randint(0, 0xFFFFFF)


__all__ = ["AccentColor", "parse_color", "random_color"]
