"""Arquivo anexado a uma mensagem."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.models.base import integer, snowflake, string


@dataclass(frozen=True, slots=True)
class Attachment:
    """Um arquivo enviado junto com uma mensagem.

    O Discord manda a URL pronta e com assinatura — não dá para montar
    sozinha a partir do ``url``, por isso ela é lida, não construída.
    """

    id: int
    filename: str
    url: str
    proxy_url: str
    size: int = 0
    content_type: str | None = None
    width: int | None = None
    height: int | None = None
    ephemeral: bool = False

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> Attachment | None:
        """`None` se faltar o ``id`` — sem ele não há anexo a baixar."""
        attachment_id = snowflake(data, "id")
        if attachment_id is None:
            return None
        return cls(
            id=attachment_id,
            filename=string(data, "filename") or "",
            url=string(data, "url") or "",
            proxy_url=string(data, "proxy_url") or "",
            size=integer(data, "size") or 0,
            content_type=string(data, "content_type"),
            width=integer(data, "width"),
            height=integer(data, "height"),
            ephemeral=data.get("ephemeral") is True,
        )

    @property
    def is_image(self) -> bool:
        """Se o anexo é uma imagem — a checagem que quase todo handler faz."""
        return bool(self.content_type and self.content_type.startswith("image/"))
