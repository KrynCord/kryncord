"""`Button` — o componente mais escrito e o mais mal construído.

discord.js divide em três classes (`CustomIdButton`, `LinkButton`,
`PremiumButton`) para resolver overload de tipagem TS — problema que
Python não tem. Aqui é **uma** classe com a tabela style × campo
validada na construção (0015, B/B2/B3), e `create_link_button` é o
único atalho, para o style que não dispara interação.

Sem `custom_id` gerado: id automático **some no submit** — o clique
chega sem com o que casar, e não há como debugar um id que ninguém
escreveu (B5).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.components.base import Component, limita
from kryncord.enums import ButtonStyle, ComponentType
from kryncord.errors import ComponentError

#: Limite do Discord para `custom_id` — 100, compartilhado com selects
#: e modals. Um lugar porque é a mesma regra do protocolo.
MAX_CUSTOM_ID = 100
MAX_LABEL = 80
MAX_URL = 512


@dataclass(frozen=True, slots=True)
class Button(Component):
    """Um botão. `LINK` e `PREMIUM` não geram interação.

    | Style | `custom_id` | `url` | `sku_id` | `label` |
    |---|---|---|---|---|
    | `PRIMARY`/`SECONDARY`/`SUCCESS`/`DANGER` | **obrigatório** | ❌ | ❌ | opcional* |
    | `LINK` | ❌ | **obrigatório** | ❌ | opcional* |
    | `PREMIUM` | ❌ | ❌ | **obrigatório** | ❌ |

    \\* `label` ou `emoji` — botão sem texto nenhum é invisível.
    """

    #: `ClassVar` sem anotação: atributo de classe, não campo. Anotar
    #: aqui o faria virar campo do dataclass — e época/número de tipo
    #: são da classe, não do objeto (0024, C2).
    type = ComponentType.BUTTON

    custom_id: str | None = None
    label: str | None = None
    emoji: str | Mapping[str, Any] | None = None
    style: ButtonStyle = ButtonStyle.PRIMARY
    url: str | None = None
    sku_id: int | None = None
    disabled: bool = False

    def __post_init__(self) -> None:
        limita(self.custom_id, MAX_CUSTOM_ID, "custom_id", onde="Button")
        limita(self.label, MAX_LABEL, "label", onde="Button")
        limita(self.url, MAX_URL, "url", onde="Button")

        self._confere_style()

    def _confere_style(self) -> None:
        """A tabela style × campo — na construção, não no HTTP.

        O Discord rejeita com erro genérico que não diz qual dos três
        campos está errado; aqui a mensagem aponta a combinação.
        """
        interativo = self.style in (
            ButtonStyle.PRIMARY,
            ButtonStyle.SECONDARY,
            ButtonStyle.SUCCESS,
            ButtonStyle.DANGER,
        )

        if interativo:
            if self.url is not None or self.sku_id is not None:
                #: Url antes do custom_id: quem escreveu `Button(url=…)`
                #: e esqueceu `style=LINK` precisa da dica do style —
                #: reclamar de custom_id mandaria procurar coisa errada.
                raise ComponentError(
                    f"Button style={self.style.name} não aceita url/sku_id — esses "
                    f"campos são de LINK e PREMIUM, que não disparam interação. "
                    f"Se a intenção era o botão de link: style=ButtonStyle.LINK."
                )
            if not self.custom_id:
                raise ComponentError(
                    "Button sem custom_id — o clique chegaria sem com o que casar, "
                    "e id gerado some no submit. Id solto ('confirm') funciona; "
                    "rota ('/painel/salvar') é o que o @responder casa."
                )

        elif self.style is ButtonStyle.LINK:
            if not self.url:
                raise ComponentError(
                    "Button style=LINK sem url — link é o motivo de o style existir. "
                    "Para o botão que dispara interação, tire o style ou use custom_id."
                )
            if self.custom_id is not None or self.sku_id is not None:
                raise ComponentError(
                    "Button LINK com custom_id/sku_id — link não dispara interação; "
                    "o id seria escrito e nunca lido"
                )

        elif self.style is ButtonStyle.PREMIUM:
            if self.sku_id is None:
                raise ComponentError(
                    "Button style=PREMIUM sem sku_id — o botão compra o SKU da loja, "
                    "e sem ele não há o que comprar"
                )
            if self.custom_id is not None or self.url is not None:
                raise ComponentError("Button PREMIUM não aceita custom_id/url")
            if self.label is not None:
                raise ComponentError(
                    "Button PREMIUM não aceita label — o título vem do SKU da loja"
                )

        if self.style is not ButtonStyle.PREMIUM and self.label is None and self.emoji is None:
            raise ComponentError(
                "Button sem label e sem emoji — botão invisível não tem como ser clicado"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": 2, "style": int(self.style)}
        if self.custom_id is not None:
            payload["custom_id"] = self.custom_id
        if self.label is not None:
            payload["label"] = self.label
        if self.emoji is not None:
            payload["emoji"] = (
                dict(self.emoji) if isinstance(self.emoji, Mapping) else {"name": self.emoji}
            )
        if self.url is not None:
            payload["url"] = self.url
        if self.sku_id is not None:
            payload["sku_id"] = str(self.sku_id)
        if self.disabled:
            payload["disabled"] = True
        return payload


def create_link_button(label: str | None = None, url: str = "", **kwargs: Any) -> Button:
    """Atalho para o único style que não dispara interação.

    `create_link_button("Docs", "https://…")` — posicional como nas
    ideias, porque é a única ordem que faz sentido ler: o texto e o
    destino.
    """
    if not url:
        raise ComponentError("create_link_button sem url — link sem destino não é link")
    return Button(label=label, url=url, style=ButtonStyle.LINK, **kwargs)


__all__ = ["MAX_CUSTOM_ID", "MAX_LABEL", "MAX_URL", "Button", "create_link_button"]
