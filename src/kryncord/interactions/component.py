"""Os campos que chegam dentro de uma interação — `values` e `fields`.

O payload é irregular de propósito: ``MESSAGE_COMPONENT`` traz
``data.values`` só para select; ``MODAL_SUBMIT`` traz
``data.components`` aninhado de duas formas diferentes (v1 com action
row, v2 com `Label` envolvendo o componente — ideias 14 e 15).
Modelar cada uma seria três modelos para o chamador desmembrar do mesmo
jeito; andar a árvore é menos código e uma forma só.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any


def valores_de_select(data: Mapping[str, Any] | None) -> tuple[str, ...]:
    """``data.values`` do select, como tupla.

    Tupla, não `list`: o Discord entregou os valores, ninguém deveria
    conseguir "adicionar" a um valor que já chegou — e um append
    silencioso aí mudaria o que o handler itera no meio do loop.
    """
    if not isinstance(data, Mapping):
        return ()
    bruto = data.get("values")
    if not isinstance(bruto, list):
        return ()
    return tuple(str(v) for v in bruto)


class ModalFields:
    """Campos de texto de um modal submetido.

        ctx.fields.get_text_input("name")
        ctx.fields["age"]
        "name" in ctx.fields
        ctx.fields.keys

    Herda de nada e não é dict: `get_text_input` é o nome da pergunta
    que se faz — `get("name")` genérico esconde que o valor é o texto
    digitado, e modal não tem outro tipo de campo editável hoje.
    """

    __slots__ = ("_campos",)

    def __init__(self, data: Mapping[str, Any] | None) -> None:
        self._campos: dict[str, str] = {}
        if isinstance(data, Mapping):
            for componente in data.get("components") or []:
                self._anda(componente)

    def _anda(self, bruto: Any) -> None:
        """Percorre a árvore nas duas formas que ela existe.

        v1: ``{components: [...]}`` (action row). v2: ``{component:
        {...}}`` (`Label` envolvendo). O campo de texto em si tem
        `custom_id` e `value` — e é o único com os dois, então é o
        critério de parada, não o `type` (que mudou de número entre
        versões da API).
        """
        if not isinstance(bruto, Mapping):
            return
        if "custom_id" in bruto and "value" in bruto:
            self._campos[str(bruto["custom_id"])] = str(bruto["value"])
            return
        for filho in bruto.get("components") or ():
            self._anda(filho)
        interno = bruto.get("component")
        if isinstance(interno, Mapping):
            self._anda(interno)

    @property
    def keys(self) -> tuple[str, ...]:
        """Os `custom_id` dos campos presentes, na ordem do modal."""
        return tuple(self._campos)

    def get_text_input(self, custom_id: str, default: str | None = None) -> str | None:
        """O texto digitado no campo, ou `default` se o campo não veio.

        Campo ausente é "não veio", não erro — o Discord não manda
        campo que o usuário não pode preencher, e `required=False`
        existe justamente para deixar vazio.
        """
        return self._campos.get(custom_id, default)

    def __getitem__(self, custom_id: str) -> str:
        try:
            return self._campos[custom_id]
        except KeyError:
            raise KeyError(
                f"campo {custom_id!r} não veio no modal; presentes: {list(self._campos)}"
            ) from None

    def __contains__(self, custom_id: object) -> bool:
        return custom_id in self._campos

    def __iter__(self) -> Iterator[str]:
        return iter(self._campos)

    def __len__(self) -> int:
        return len(self._campos)
