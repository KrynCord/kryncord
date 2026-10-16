"""O pai de todo componente — `era`, `to_dict` e a travessia.

Duas coisas moram aqui porque **todo** componente precisa delas, e
espalhar seria uma tabela por arquivo:

- `era` — a resposta do X2: cada componente declara sua época
  (`"v1"`, `"v2"`, `"both"`), e a validação da ideia 18 §4 consulta
  o atributo em vez de uma lista de nomes espalhada. Um lugar só
  decide o que é legado e o que é V2.
- `walk()` — a travessia da árvore. `Section`, `Container` e
  `Label` sobrescrevem para descer nos filhos; a validação de
  contagem (40 componentes, 4000 caracteres) e a de `custom_id`
  duplicado são um `for` em cima dela. Zero I/O, 100% testável.

`ClassVar` de propósito: a época é da **classe**. Campo de instância
mentiria sobre o que é fixo — `Button` não muda de era por objeto.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, ClassVar, Literal

from kryncord.enums import ComponentType
from kryncord.errors import ComponentError

#: A época de um componente. `both` é o que faz V1 e V2 conviverem sem
#: duplicar builder: `ActionRow`, botões e selects são os mesmos.
#: `modal` é o que impede componente de formulário de vazar para
#: mensagem: `TextInput` e companhia **só** existem dentro de `Label`.
Era = Literal["v1", "v2", "both", "modal"]


class Component:
    """Pai de todo builder de componente.

    Não é dataclass: os filhos é que são `@dataclass(frozen=True,
    slots=True)` (0015). A herança existe para `to_dict`, `walk` e as
    `ClassVar` — superfície, não campos.
    """

    type: ClassVar[ComponentType]
    era: ClassVar[Era] = "both"

    def to_dict(self) -> dict[str, Any]:
        """O payload camelCase que vai no `json=`.

        A única função que conhece o **número** do tipo — o resto do
        código fala em classes. É isso que torna o módulo testável
        sem Discord: comparar dict é comparar payload.
        """
        raise NotImplementedError(f"{type(self).__name__} não serializa")

    def walk(self) -> Iterator[Component]:
        """A árvore a partir daqui, inclusive este componente."""
        yield self


def limita(valor: str | None, maximo: int, nome: str, onde: str = "") -> None:
    """Valida limite de string na montagem, com o campo e o tamanho.

    Truncar é a decisão que a V3 rejeitou: layout cortado é layout
    errado — o botão que diz "Confirmar ca…" não confirma nada.

    `onde` entra na mensagem quando o limite é de um componente dentro
    de outro (`components[2].label`), porque "limite excedido" sem
    caminho não ajuda num painel de 5 rows.
    """
    if valor is None or len(valor) <= maximo:
        return
    prefixo = f"{onde}." if onde else ""
    raise ComponentError(
        f"{prefixo}{nome} tem {len(valor)} caracteres, máximo {maximo} — "
        f"truncar mudaria o que o usuário lê; encurte na fonte"
    )
