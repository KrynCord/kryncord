"""Builders de payloads mais amplos, separados dos modelos recebidos.

Embeds, mensagens — o que **vai** para o Discord e não é componente de
interface (componentes moram em `components/`, separados por tipo, com
validação estrutural própria).

Separação proposital: `models/` é o que **chega** do Discord,
`builders/` é o que **vai**. Misturar os dois gera classes que têm 30
campos opcionais e nenhum garantido.
"""

from kryncord.builders.embed import (
    ZERO_WIDTH,
    Embed,
    EmbedAuthor,
    EmbedField,
    EmbedFooter,
    EmbedImage,
    create_embed,
)
from kryncord.builders.messages import ReplyOptions, normalizar_mensagem

__all__ = [
    "ZERO_WIDTH",
    "Embed",
    "EmbedAuthor",
    "EmbedField",
    "EmbedFooter",
    "EmbedImage",
    "ReplyOptions",
    "create_embed",
    "normalizar_mensagem",
]
