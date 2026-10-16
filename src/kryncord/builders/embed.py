"""`Embed` e a família — o card da geração V1.

Embed é legado e **continua válido** (ideia 18: "se cabe num embed,
faça V1"). A classe segue as regras do resto da biblioteca:
`@dataclass(frozen=True, slots=True)`, validação no construtor (0015),
e `to_dict()` como única função que fala payload.

O que a `0015` respondeu e está em vigor aqui:

- `source`/`index` existem em `create_embed` (o "copiar de" — `from`
  é reservado em Python);
- `extends` **não** existe — composição se faz com os argumentos;
- `as_array` **não** existe — "um só item sem delimitador" não é
  formato;
- `"Random"` é do `create_embed`, não da classe (E4): o **mesmo**
  embed tem que renderizar igual sempre que for construído.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from kryncord.components.colors import parse_color, random_color
from kryncord.errors import ComponentError

MAX_TITULO = 256
MAX_DESCRICAO = 4096
MAX_CAMPOS = 25
MAX_NOME_CAMPO = 256
MAX_VALOR_CAMPO = 1024
MAX_FOOTER = 2048
MAX_AUTOR = 256
MAX_TOTAL = 6000

#: O Discord descarta `name`/`value` de string vazia. Campo "vazio"
#: existe na prática como separador de coluna — e o jeito dele é o
#: zero-width space (E5).
ZERO_WIDTH = "​"


@dataclass(frozen=True, slots=True)
class EmbedField:
    """Um campo `name`/`value` do embed."""

    name: str
    value: str
    inline: bool = False

    def __post_init__(self) -> None:
        if len(self.name) > MAX_NOME_CAMPO:
            raise ComponentError(
                f"EmbedField.name com {len(self.name)} caracteres, máximo {MAX_NOME_CAMPO}"
            )
        if len(self.value) > MAX_VALOR_CAMPO:
            raise ComponentError(
                f"EmbedField.value com {len(self.value)} caracteres, máximo {MAX_VALOR_CAMPO}"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name, "value": self.value}
        if self.inline:
            payload["inline"] = True
        return payload


@dataclass(frozen=True, slots=True)
class EmbedFooter:
    """Rodapé — texto e ícone opcional."""

    text: str
    icon_url: str | None = None

    def __post_init__(self) -> None:
        if len(self.text) > MAX_FOOTER:
            raise ComponentError(
                f"EmbedFooter.text com {len(self.text)} caracteres, máximo {MAX_FOOTER}"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": self.text}
        if self.icon_url is not None:
            payload["icon_url"] = self.icon_url
        return payload


@dataclass(frozen=True, slots=True)
class EmbedAuthor:
    """Autor — nome, link e ícone opcionais."""

    name: str
    url: str | None = None
    icon_url: str | None = None

    def __post_init__(self) -> None:
        if len(self.name) > MAX_AUTOR:
            raise ComponentError(
                f"EmbedAuthor.name com {len(self.name)} caracteres, máximo {MAX_AUTOR}"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name}
        if self.url is not None:
            payload["url"] = self.url
        if self.icon_url is not None:
            payload["icon_url"] = self.icon_url
        return payload


@dataclass(frozen=True, slots=True)
class EmbedImage:
    """Imagem por URL — a forma tipada; `str` e `dict` também passam."""

    url: str

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url}


@dataclass(frozen=True, slots=True)
class Embed:
    """O card V1. `era = "v1"` (ideia 18 §7): nunca numa árvore V2.

        Embed(
            title="Perfil",
            description=["Linha um", "", "Linha três"],   # junta com \\n
            color="Blurple",
            author=EmbedAuthor("Bot", icon_url="https://…"),
            thumbnail="https://…",                          # str, dict ou EmbedImage
            fields=[EmbedField("Nível", "42", inline=True), ("XP", "1200")],
            footer="ID: 123",
            timestamp=True,                                 # agora, em UTC
        )

    `description` como lista é o que eliminou o `brBuilder` do TS
    (E3) — juntar linhas com `\\n` é o caso comum, e `["a", "", "c"]`
    preserva o parágrafo vazio.
    """

    title: str | None = None
    description: str | Sequence[str] | None = None
    url: str | None = None
    color: str | int | None = None
    timestamp: bool | datetime | str | None = None
    footer: str | Mapping[str, Any] | EmbedFooter | None = None
    image: str | Mapping[str, Any] | EmbedImage | Any | None = None
    thumbnail: str | Mapping[str, Any] | EmbedImage | Any | None = None
    author: str | Mapping[str, Any] | EmbedAuthor | None = None
    fields: Iterable[EmbedField | Mapping[str, Any] | Sequence[Any] | str] = ()

    era = "v1"

    def __post_init__(self) -> None:
        if self.title is not None and len(self.title) > MAX_TITULO:
            raise ComponentError(
                f"Embed.title com {len(self.title)} caracteres, máximo {MAX_TITULO}"
            )

        descricao = _descricao(self.description)
        if len(descricao) > MAX_DESCRICAO:
            raise ComponentError(
                f"Embed.description com {len(descricao)} caracteres, máximo {MAX_DESCRICAO}"
            )

        if isinstance(self.color, str) and self.color.strip().lower() == "random":
            raise ComponentError(
                'cor "Random" na classe Embed — o mesmo embed renderizaria diferente '
                "a cada construção; use create_embed(color='Random') ou random_color()"
            )

        object.__setattr__(self, "description", descricao)
        object.__setattr__(
            self, "color", parse_color(self.color) if self.color is not None else None
        )
        object.__setattr__(self, "timestamp", _timestamp(self.timestamp))
        object.__setattr__(self, "footer", _footer(self.footer))
        object.__setattr__(self, "author", _autor(self.author))
        object.__setattr__(self, "image", _imagem(self.image))
        object.__setattr__(self, "thumbnail", _imagem(self.thumbnail))

        #: Normaliza **antes** do total: a soma percorre campos já
        #: garantidos como `EmbedField` — percorrer o cru seria somar
        #: `len` de dict e de str na mesma iteração.
        campos = _campos(self.fields)
        object.__setattr__(self, "fields", campos)

        total = (
            len(self.title or "")
            + len(descricao)
            + len(getattr(self.footer, "text", "") or "")
            + len(getattr(self.author, "name", "") or "")
            + sum(len(f.name) + len(f.value) for f in campos)
        )
        if total > MAX_TOTAL:
            #: O limite que mais passa batido (ideia 16 §2): cabem 10
            #: campos de 1024 e ainda estoura. É a única validação que
            #: precisa de travessia.
            raise ComponentError(
                f"Embed com {total} caracteres somados, máximo {MAX_TOTAL} — "
                f"é a soma de title + description + footer + author + campos"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.title is not None:
            payload["title"] = self.title
        if self.description:
            payload["description"] = self.description
        if self.url is not None:
            payload["url"] = self.url
        if self.color is not None:
            payload["color"] = self.color
        if self.timestamp is not None:
            payload["timestamp"] = self.timestamp
        if self.footer is not None:
            payload["footer"] = self.footer.to_dict()  # type: ignore[union-attr]
        if self.image is not None:
            payload["image"] = self.image.to_dict()  # type: ignore[union-attr]
        if self.thumbnail is not None:
            payload["thumbnail"] = self.thumbnail.to_dict()  # type: ignore[union-attr]
        if self.author is not None:
            payload["author"] = self.author.to_dict()  # type: ignore[union-attr]
        #: O campo é `Iterable[...]` no construtor porque aceita dict e
        #: tuple; depois do `__post_init__` é sempre `tuple[EmbedField,
        #: ...]` — o cast declara ao mypy o que o normalizador garantiu.
        campos = cast("tuple[EmbedField, ...]", self.fields)
        if campos:
            payload["fields"] = [c.to_dict() for c in campos]
        return payload


# ----------------------------------------------------------------------
# Normalização — a tabela da ideia 16 §5
# ----------------------------------------------------------------------


def _descricao(bruto: str | Sequence[str] | None) -> str:
    if bruto is None:
        return ""
    if isinstance(bruto, str):
        return bruto
    return "\n".join(bruto)


def _timestamp(bruto: bool | datetime | str | None) -> str | None:
    if bruto is None or bruto is False:
        return None
    if bruto is True:
        return datetime.now(UTC).isoformat()
    if isinstance(bruto, datetime):
        return bruto.astimezone(UTC).isoformat()
    return bruto


def _footer(bruto: Any) -> EmbedFooter | None:
    if bruto is None:
        return None
    if isinstance(bruto, EmbedFooter):
        return bruto
    if isinstance(bruto, str):
        return EmbedFooter(text=bruto)
    if isinstance(bruto, Mapping):
        return EmbedFooter(text=str(bruto.get("text", "")), icon_url=bruto.get("icon_url"))
    raise ComponentError(f"footer {bruto!r} — str, dict ou EmbedFooter")


def _autor(bruto: Any) -> EmbedAuthor | None:
    if bruto is None:
        return None
    if isinstance(bruto, EmbedAuthor):
        return bruto
    if isinstance(bruto, str):
        return EmbedAuthor(name=bruto)
    if isinstance(bruto, Mapping):
        return EmbedAuthor(
            name=str(bruto.get("name", "")),
            url=bruto.get("url"),
            icon_url=bruto.get("icon_url"),
        )
    raise ComponentError(f"author {bruto!r} — str, dict ou EmbedAuthor")


def _imagem(bruto: Any) -> EmbedImage | None:
    if bruto is None:
        return None
    if isinstance(bruto, EmbedImage):
        return bruto
    if isinstance(bruto, str):
        return EmbedImage(url=bruto)
    if isinstance(bruto, Mapping):
        if "url" not in bruto:
            raise ComponentError(f"imagem {bruto!r} sem url")
        return EmbedImage(url=str(bruto["url"]))
    if hasattr(bruto, "url"):
        #: `Attachment` do modelo — a ideia 16 §5.
        return EmbedImage(url=str(bruto.url))
    raise ComponentError(
        f"imagem {bruto!r} — str, dict, EmbedImage ou Attachment; bytes precisa "
        f"do upload de files, que a camada api/ ainda não faz"
    )


def _campos(bruto: Iterable[Any]) -> tuple[EmbedField, ...]:
    saida: list[EmbedField] = []
    for item in bruto:
        if isinstance(item, EmbedField):
            saida.append(item)
        elif isinstance(item, Mapping):
            saida.append(
                EmbedField(
                    name=str(item.get("name", "")),
                    value=str(item.get("value", "")),
                    inline=bool(item.get("inline", False)),
                )
            )
        elif isinstance(item, str):
            #: Campo sem valor é inválido para o Discord — o separador
            #: de coluna usa o zero-width (E5).
            saida.append(EmbedField(name=item, value=ZERO_WIDTH))
        elif isinstance(item, Sequence) and len(item) == 2:
            saida.append(EmbedField(name=str(item[0]), value=str(item[1])))
        else:
            raise ComponentError(f"campo de embed {item!r} — EmbedField, dict, tuple ou str")
    if len(saida) > MAX_CAMPOS:
        raise ComponentError(f"{len(saida)} campos, máximo {MAX_CAMPOS}")
    return tuple(saida)


# ----------------------------------------------------------------------
# create_embed — o facilitador
# ----------------------------------------------------------------------


def create_embed(
    *,
    source: Any = None,
    index: int = 0,
    color: str | int | None = None,
    **kwargs: Any,
) -> Embed:
    """O facilitador — o `createEmbed` da base TS, com os nomes Python.

        create_embed(title="Painel", color="Green", footer="Equipe")
        create_embed(color="Random")                       # sorte explícita
        create_embed(source=mensagem, index=0, color="Red")  # copia e ajusta

    A ordem é documento, não detalhe: **`source` → kwargs**. `extends`
    não existe (0015) — composição se faz passando os argumentos.
    """
    if source is not None:
        originais = getattr(source, "embeds", None)
        if originais is None:
            #: O modelo `Message` guarda embeds no `raw` (0003: dado
            #: puro, sem parse de builder). `source.embeds` existe em
            #: mensagem que a gente montou; no payload do Discord, o
            #: dict cru é o que há.
            bruto_raw = getattr(source, "raw", None) or {}
            originais = bruto_raw.get("embeds") if isinstance(bruto_raw, Mapping) else None
        if not originais or index >= len(originais):
            raise ComponentError(
                f"create_embed: source não tem embed {index} — "
                f"tem {len(originais) if originais else 0}"
            )
        bruto = originais[index]
        if isinstance(bruto, Embed):
            return _copia_ajustada(bruto, kwargs, color)
        if isinstance(bruto, Mapping):
            return _copia_de_raw(bruto, kwargs, color)
        raise ComponentError(
            f"create_embed: embed de source é {type(bruto).__name__} — "
            f"esperado Embed do builder ou dict do payload"
        )

    cor = random_color() if isinstance(color, str) and color.strip().lower() == "random" else color
    return Embed(color=cor, **kwargs)


def _copia_ajustada(base: Embed, kwargs: dict[str, Any], color: Any) -> Embed:
    """`dataclasses.replace` do embed — o que mudou, muda; o resto fica."""
    #: `dict[str, Any]` explícito: sem ele o mypy infere a união dos
    #: tipos dos valores e reclama do splat em parâmetros tipados — o
    #: `__post_init__` é quem garante o resto.
    campos: dict[str, Any] = {
        "title": base.title,
        "description": base.description,
        "url": base.url,
        "color": base.color,
        "timestamp": base.timestamp,
        "footer": base.footer,
        "image": base.image,
        "thumbnail": base.thumbnail,
        "author": base.author,
        "fields": base.fields,
    }
    if color is not None:
        campos["color"] = color
    campos.update(kwargs)
    return Embed(**campos)


def _copia_de_raw(bruto: Mapping[str, Any], kwargs: dict[str, Any], color: Any) -> Embed:
    """Cópia a partir do payload cru — só as chaves que o builder tem.

    O protocolo manda campos sem tradução no V1 (`video`, `provider`,
    `type`) — copiá-los seria fingir que o builder os suporta. O que
    não tem construtor fica de fora, e o ajuste de `kwargs` vence.
    """
    conhecidos = {
        "title",
        "description",
        "url",
        "color",
        "timestamp",
        "footer",
        "image",
        "thumbnail",
        "author",
        "fields",
    }
    campos: dict[str, Any] = {k: v for k, v in bruto.items() if k in conhecidos}
    if color is not None:
        campos["color"] = color
    campos.update(kwargs)
    return Embed(**campos)


__all__ = [
    "ZERO_WIDTH",
    "Embed",
    "EmbedAuthor",
    "EmbedField",
    "EmbedFooter",
    "EmbedImage",
    "create_embed",
]
