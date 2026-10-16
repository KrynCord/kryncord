"""Autenticação de bot.

O objetivo aqui é uma coisa só: **o token não pode vazar**.

Não para o Discord — o Discord precisa dele. Para o nosso log, para o
traceback, para a mensagem de erro que o usuário vai colar num issue
público. Vazamento de token é o incidente mais comum e mais evitável de
biblioteca Discord: aparece em ``repr()`` de um objeto que alguém mandou
pro ``logging`` por engano, ou numa ``ValueError`` que concatena o
request inteiro.

Então `Token` mascara em ``repr``, ``str`` e no formato ``{}``. Quem
precisar do valor cru acessa ``.value`` — explicitamente, com barra no
meio do caminho.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

#: Prefixo do header Authorization. O portal de desenvolvedores mostra o
#: token já com o prefixo; aqui separamos para não mandar "Bot Bot ...".
DEFAULT_PREFIX = "Bot"

#: Quantos caracteres do token aparecem antes de virar asteriscos.
#: Suficiente para distinguir "meu token de produção" de "o de teste".
_VISIBLE_TAIL = 4

AUTHORIZATION_HEADER = "Authorization"


def _mask(token: str) -> str:
    if not token:
        return "<vazio>"
    if len(token) <= _VISIBLE_TAIL:
        return "***"
    return f"***{token[-_VISIBLE_TAIL:]}"


@dataclass(frozen=True, slots=True)
class Token:
    """Credencial de bot, com ``repr`` seguro."""

    value: str
    prefix: str = DEFAULT_PREFIX

    @property
    def masked(self) -> str:
        """Forma segura para log: ``Bot ***abcd``."""
        return f"{self.prefix} {_mask(self.value)}"

    @property
    def header_value(self) -> str:
        """Valor do header ``Authorization``. O único lugar que lê cru."""
        return f"{self.prefix} {self.value}"

    def __repr__(self) -> str:
        # Sobrescrito de propósito: o repr padrão de dataclass imprime
        # todos os campos, token incluso.
        return f"Token({self.masked!r})"

    def __str__(self) -> str:
        return self.masked


def build_auth_header(token: Token | None) -> Mapping[str, str]:
    """Monta o header de autorização, ou dict vazio se não houver token.

    `None` não vira ``Authorization: None`` — vira ausência total do
    header. É o caso de endpoints públicos (e de quem ainda não configurou
    o bot e vai receber um 401 legível).
    """
    if token is None:
        return {}
    return {AUTHORIZATION_HEADER: token.header_value}
