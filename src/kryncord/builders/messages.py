"""`ReplyOptions` e a normalização de mensagem — onde V1 encontra V2.

Este é o único lugar que conhece os dois sistemas (ideia 18 §4). Tudo
que responde mensagem converge aqui: os `kwargs` de `ctx.reply` na
camada `api/` passam por `normalizar_mensagem`, e o `ReplyOptions` é
a forma tipada dos mesmos argumentos.

`normalizar_mensagem` é **aditiva**: quem já mandava dict cru continua
funcionando — dict cru entra, dict cru sai. O que muda é que
componente, embed e flag agora serializam de verdade:

| Entrada | Saída |
|---|---|
| `Component` / lista de | `to_dict()` de cada |
| `Embed` / lista de | `to_dict()` de cada |
| `flags=[MessageFlags.X]` / `MessageFlags.X` / `int` | inteiro OU-ed |
| `v2=True` | pop + `IS_COMPONENTS_V2` no inteiro de flags |
| `ephemeral=True` | pop + `EPHEMERAL` no inteiro de flags |

O `ephemeral=True` é correção de bug real: como chave de payload ele é
**silenciosamente ignorado** pelo Discord — a mensagem aparecia para
todo mundo, sem erro em lugar nenhum. A flag é `flags: 64`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from kryncord.builders.embed import Embed
from kryncord.components.base import Component
from kryncord.components.validation import parse_flags, validate_message
from kryncord.enums import MessageFlags
from kryncord.errors import ComponentError


@dataclass(frozen=True, slots=True)
class ReplyOptions:
    """Os argumentos de uma resposta, tipados e validados.

        opts = ReplyOptions(content="Escolha:", components=[row])
        await ctx.reply(**opts.to_payload())

    `to_payload()` devolve o `dict` pronto — validado pela tabela
    V1 × V2 e serializado. Passar objeto direto em `ctx.reply(...)`
    também funciona: os `kwargs` passam pela mesma normalização
    na camada `api/`.
    """

    content: str | None = None
    embeds: Iterable[Embed | Mapping[str, Any]] = ()
    components: Iterable[Component] = ()
    flags: MessageFlags | int | Iterable[MessageFlags | int] | None = None
    v2: bool = False

    def to_payload(self) -> dict[str, Any]:
        return normalizar_mensagem(
            {
                "content": self.content,
                "embeds": tuple(self.embeds) or None,
                "components": tuple(self.components) or None,
                "flags": self.flags,
                "v2": self.v2,
            }
        )


def normalizar_mensagem(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Serializa e valida os argumentos de resposta — o ponto de convergência.

    Ordem das coisas, porque a ordem é documento:

    1. `v2`/`ephemeral` viram **bits** no inteiro de flags;
    2. `flags` vira inteiro (de lista, `IntFlag` ou `int`);
    3. a tabela V1 × V2 (`validate_message`) reclama das combinações
       que o Discord trataria pior — ignora em silêncio ou rejeita
       genérico;
    4. componente e embed viram payload.

    A validação roda **antes** da serialização: os objetos precisam
    existir ainda, para o erro carregar `type` e `era`.
    """
    saida = dict(kwargs)

    flags = parse_flags(saida.get("flags"))
    if saida.pop("v2", False):
        flags = (flags or 0) | int(MessageFlags.IS_COMPONENTS_V2)
    if saida.pop("ephemeral", False):
        flags = (flags or 0) | int(MessageFlags.EPHEMERAL)
    if flags is not None:
        saida["flags"] = flags
    else:
        saida.pop("flags", None)

    componentes = _lista(saida.get("components"))
    embeds = _lista(saida.get("embeds"))

    if componentes is not None or embeds is not None or flags is not None:
        validate_message(
            content=saida.get("content"),
            embeds=embeds or (),
            components=componentes or (),
            flags=flags,
        )

    if componentes is not None:
        saida["components"] = [c.to_dict() for c in componentes]
    if embeds is not None:
        saida["embeds"] = [_embed_dict(e) for e in embeds]

    return {k: v for k, v in saida.items() if v is not None}


def _lista(bruto: Any) -> tuple[Any, ...] | None:
    """`None` quando a chave não veio; tupla quando veio.

    Distinguir os dois é o que faz `components=()` (chave que veio,
    lista vazia) significar algo para a validação da flag órfã — e
    ausência total continuar ausente.
    """
    if bruto is None:
        return None
    if isinstance(bruto, (list, tuple)):
        return tuple(bruto)
    return (bruto,)


def _embed_dict(bruto: Any) -> dict[str, Any]:
    if isinstance(bruto, Embed):
        return bruto.to_dict()
    if isinstance(bruto, Mapping):
        return dict(bruto)
    raise ComponentError(f"embed {type(bruto).__name__} — Embed do builder ou dict do payload")


__all__ = ["ReplyOptions", "normalizar_mensagem"]
