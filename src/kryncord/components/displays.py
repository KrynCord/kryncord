"""Components V2 — a mensagem como árvore de layouts.

A geração nova joga `content`/`embeds` para dentro de um sistema só:
`Container` > `Section` > `TextDisplay`. Os builders aqui são **puros**
— nenhum adiciona `IS_COMPONENTS_V2` sozinho. A flag é da mensagem, e
auto-flag por presença de `Container` é o comportamento invisível que
a `0015` rejeitou: funcionaria no teste e mudaria o payload no servidor.

Três classes aceitam construção variadic (`Container("#5865F2", td1,
td2)`), porque as ideias as escrevem assim. Elas têm `__init__`
próprio por cima do dataclass — que segue fornecendo `frozen`, `eq` e
`repr`, e guardando o valor **normalizado** no campo declarado.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, cast

from kryncord.components.base import Component
from kryncord.components.buttons import Button
from kryncord.components.colors import AccentColor, parse_color
from kryncord.enums import ComponentType
from kryncord.errors import ComponentError

MAX_FILHOS = 40
MAX_TEXTO_TOTAL = 4000
MAX_TEXTOS_SECAO = 3
MAX_IMAGENS = 10
MAX_URL_MIDIA = 2048
MAX_ALT_TEXT = 1024


class SeparatorSize(IntEnum):
    """Enum de builder — mora aqui, não no `enums.py` (mesma régua do
    `TextInputStyle`, L3)."""

    SMALL = 1
    LARGE = 2


@dataclass(frozen=True, slots=True)
class TextDisplay(Component):
    """Texto markdown. O `content` da mensagem V2.

    `era = "v2"`: sem a flag, o Discord rejeita — e é o validador da
    mensagem que diz isso, com o caminho, não um 400 genérico.
    """

    type = ComponentType.TEXT_DISPLAY

    content: str

    era = "v2"

    def __post_init__(self) -> None:
        if not self.content:
            raise ComponentError("TextDisplay vazio — texto vazio é componente inexistente")

    def to_dict(self) -> dict[str, Any]:
        return {"type": 10, "content": self.content}


@dataclass(frozen=True, slots=True)
class Separator(Component):
    """Espaço ou divisor.

    | Forma | `spacing` | `divider` |
    |---|---|---|
    | `Separator.default()` | `SMALL` | `True` |
    | `Separator.large()` | `LARGE` | `True` |
    | `Separator.small()` | `SMALL` | `False` — só o espaço, sem linha |

    "Espaço pequeno" da ideia 13 §5.1 é spacing sem divisor — é a
    única das três formas em que a linha não aparece.
    """

    type = ComponentType.SEPARATOR

    spacing: SeparatorSize = SeparatorSize.SMALL
    divider: bool = True

    era = "v2"

    @classmethod
    def default(cls) -> Separator:
        return cls(spacing=SeparatorSize.SMALL, divider=True)

    @classmethod
    def large(cls) -> Separator:
        return cls(spacing=SeparatorSize.LARGE, divider=True)

    @classmethod
    def small(cls) -> Separator:
        return cls(spacing=SeparatorSize.SMALL, divider=False)

    def to_dict(self) -> dict[str, Any]:
        return {"type": 14, "spacing": int(self.spacing), "divider": self.divider}


@dataclass(frozen=True, slots=True)
class Thumbnail(Component):
    """Imagem pequena — só como `accessory` de `Section`."""

    type = ComponentType.THUMBNAIL

    url: str
    description: str | None = None
    spoiler: bool = False

    era = "v2"

    def __post_init__(self) -> None:
        if len(self.url) > MAX_URL_MIDIA:
            raise ComponentError(
                f"Thumbnail: url com {len(self.url)} caracteres, máximo {MAX_URL_MIDIA}"
            )
        if self.description is not None and len(self.description) > MAX_ALT_TEXT:
            raise ComponentError(f"Thumbnail: description com mais de {MAX_ALT_TEXT} caracteres")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": 11, "media": {"url": self.url}}
        if self.description is not None:
            payload["description"] = self.description
        if self.spoiler:
            payload["spoiler"] = True
        return payload


@dataclass(frozen=True, slots=True)
class MediaGalleryItem:
    """Uma imagem da galeria — url, alt text, spoiler."""

    url: str
    description: str | None = None
    spoiler: bool = False

    def __post_init__(self) -> None:
        if len(self.url) > MAX_URL_MIDIA:
            raise ComponentError(
                f"mídia com url de {len(self.url)} caracteres, máximo {MAX_URL_MIDIA}"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"media": {"url": self.url}}
        if self.description is not None:
            payload["description"] = self.description
        if self.spoiler:
            payload["spoiler"] = True
        return payload


@dataclass(frozen=True, slots=True)
class MediaGallery(Component):
    """Grade de até 10 imagens.

    MediaGallery("https://exemplo.com/1.png", "https://exemplo.com/2.png")
    MediaGallery({"url": "...", "spoiler": True})
    """

    type = ComponentType.MEDIA_GALLERY

    items: tuple[MediaGalleryItem, ...] = ()

    era = "v2"

    def __init__(self, *fontes: Any, items: Iterable[Any] = ()) -> None:
        bruto = tuple(fontes) or tuple(items)
        if not bruto:
            raise ComponentError("MediaGallery sem imagens — galeria vazia não renderiza")
        if len(bruto) > MAX_IMAGENS:
            raise ComponentError(f"MediaGallery com {len(bruto)} imagens, máximo {MAX_IMAGENS}")
        object.__setattr__(self, "items", tuple(_item(f) for f in bruto))

    def to_dict(self) -> dict[str, Any]:
        return {"type": 12, "items": [i.to_dict() for i in self.items]}


def _item(fonte: Any) -> MediaGalleryItem:
    if isinstance(fonte, MediaGalleryItem):
        return fonte
    if isinstance(fonte, str):
        return MediaGalleryItem(url=fonte)
    if isinstance(fonte, Mapping):
        if "url" not in fonte:
            raise ComponentError(f"item de mídia {fonte!r} sem url")
        return MediaGalleryItem(
            url=str(fonte["url"]),
            description=fonte.get("description"),
            spoiler=bool(fonte.get("spoiler", False)),
        )
    if hasattr(fonte, "url"):
        #: `Attachment` do modelo — a tabela da ideia 13 §6.
        return MediaGalleryItem(url=str(fonte.url))
    raise ComponentError(f"item de mídia {fonte!r} — str, dict ou Attachment")


@dataclass(frozen=True, slots=True)
class File(Component):
    """Arquivo anexado — exposto explicitamente no V2.

    `File("attachment://documento.pdf")` — o esquema `attachment://`
    referencia um arquivo do upload da mesma mensagem.
    """

    type = ComponentType.FILE

    url: str
    spoiler: bool = False

    era = "v2"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": 13, "file": {"url": self.url}}
        if self.spoiler:
            payload["spoiler"] = True
        return payload


@dataclass(frozen=True, slots=True)
class Section(Component):
    """Texto (1–3 `TextDisplay`) + um accessory (`Thumbnail` ou `Button`).

        Section(TextDisplay("**Status**\\nOnline"), accessory=Thumbnail(url="..."))
        Section(TextDisplay("a"), TextDisplay("b"), accessory=Button(...))

    Sem accessory não existe `Section` — use `TextDisplay` solto
    (ideia 13 §4: a regra é do protocolo).
    """

    type = ComponentType.SECTION

    components: tuple[TextDisplay, ...] = ()
    accessory: Component | None = None

    era = "v2"

    def __init__(self, *textos: Any, accessory: Component | None = None) -> None:
        normalizados = tuple(_texto_da_secao(t) for t in textos)
        if not (1 <= len(normalizados) <= MAX_TEXTOS_SECAO):
            raise ComponentError(
                f"Section com {len(normalizados)} TextDisplay, aceito 1..{MAX_TEXTOS_SECAO} — "
                f"mais que isso é Container; menos é nada"
            )
        if accessory is None:
            raise ComponentError(
                "Section sem accessory — sem a miniatura/botão lateral não é Section; "
                "use TextDisplay solto"
            )
        if not isinstance(accessory, (Thumbnail, Button)):
            raise ComponentError(
                f"accessory {type(accessory).__name__} — só Thumbnail ou Button; "
                f"outro componente ali não renderiza"
            )
        object.__setattr__(self, "components", normalizados)
        object.__setattr__(self, "accessory", accessory)

    def walk(self) -> Iterator[Component]:
        yield self
        yield from self.components
        yield cast("Component", self.accessory)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": 9,
            "components": [t.to_dict() for t in self.components],
            "accessory": self.accessory.to_dict(),  # type: ignore[union-attr]
        }


def _texto_da_secao(bruto: Any) -> TextDisplay:
    if isinstance(bruto, TextDisplay):
        return bruto
    if isinstance(bruto, str):
        return TextDisplay(bruto)
    raise ComponentError(
        f"Section aceita TextDisplay (ou str), veio {type(bruto).__name__} — "
        f"é o texto da seção, não um componente qualquer"
    )


@dataclass(frozen=True, slots=True)
class Container(Component):
    """Agrupador com barra lateral colorida — o "card" do V2.

        Container("#5865F2", TextDisplay("# Título"), TextDisplay("Corpo"))
        Container(TextDisplay("sem cor também funciona"))

    Um nível só: `Container` dentro de `Container` é erro, e quem
    reclama é o `__init__` — na montagem, não no render.
    """

    type = ComponentType.CONTAINER

    components: tuple[Component, ...] = ()
    accent_color: int | None = None
    spoiler: bool = False

    era = "v2"

    def __init__(
        self,
        *args: Any,
        components: Iterable[Component] = (),
        accent_color: str | int | AccentColor | None = None,
        spoiler: bool = False,
    ) -> None:
        filhos = tuple(args) + tuple(components)
        cor = accent_color
        if args and not isinstance(args[0], Component):
            #: `Container("#5865F2", td)` — cor na frente, como nas
            #: ideias. Só entra se o primeiro **não** for componente,
            #: para `Container(td)` continuar funcionando.
            cor = args[0]
            filhos = tuple(args[1:]) + tuple(components)

        if not filhos:
            raise ComponentError("Container sem filhos — container vazio não renderiza")
        for filho in filhos:
            if isinstance(filho, Container):
                raise ComponentError(
                    "Container dentro de Container — um nível só é regra do protocolo"
                )

        object.__setattr__(self, "components", filhos)
        object.__setattr__(self, "accent_color", parse_color(cor) if cor is not None else None)
        object.__setattr__(self, "spoiler", bool(spoiler))

    def walk(self) -> Iterator[Component]:
        yield self
        for filho in self.components:
            yield from filho.walk()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": 17, "components": [c.to_dict() for c in self.components]}
        if self.accent_color is not None:
            payload["accent_color"] = self.accent_color
        if self.spoiler:
            payload["spoiler"] = True
        return payload


# ----------------------------------------------------------------------
# Helpers de fábrica — o "create_x" da base TS (ideia 13 §5.2)
# ----------------------------------------------------------------------


def create_text_display(text: str) -> TextDisplay:
    return TextDisplay(text)


def create_separator(large: bool = False, divider: bool = True) -> Separator:
    return Separator(spacing=SeparatorSize.LARGE if large else SeparatorSize.SMALL, divider=divider)


def create_thumbnail(url: str, **kwargs: Any) -> Thumbnail:
    return Thumbnail(url=url, **kwargs)


def create_media_gallery(*urls: Any, **kwargs: Any) -> MediaGallery:
    return MediaGallery(*urls, **kwargs)


def create_file(url: str, **kwargs: Any) -> File:
    return File(url=url, **kwargs)


def create_section(*textos: Any, accessory: Component | None = None) -> Section:
    return Section(*textos, accessory=accessory)


def create_container(
    cor: str | int | AccentColor | None = None, *filhos: Component, **kwargs: Any
) -> Container:
    return Container(cor, *filhos, **kwargs)


__all__ = [
    "MAX_FILHOS",
    "MAX_TEXTOS_SECAO",
    "MAX_TEXTO_TOTAL",
    "Container",
    "File",
    "MediaGallery",
    "MediaGalleryItem",
    "Section",
    "Separator",
    "SeparatorSize",
    "TextDisplay",
    "Thumbnail",
    "create_container",
    "create_file",
    "create_media_gallery",
    "create_section",
    "create_separator",
    "create_text_display",
    "create_thumbnail",
]
