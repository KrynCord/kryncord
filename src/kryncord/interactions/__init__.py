"""Interações recebidas do Discord e suas respostas.

A separação de papéis:

| Peça | Dono |
|---|---|
| `models.interaction.Interaction` | o payload, dado puro |
| `interactions.response.InteractionContext` | o estado da resposta |
| `interactions.component.ModalFields` | os campos do modal submetido |

O estado **não** mora no modelo. `Interaction` é `frozen` (`0003`), e o
mesmo payload pode ser entregue a mais de um contexto durante um
dispatch — guardar a máquina nele seria imutabilidade quebrada por
dentro.

A máquina tem quatro estados e é o único ponto que decide se uma
resposta pode ser mandada. Centralizar isso é o que torna a ordem
testável sem rede: violar a sequência é `InteractionStateError` nosso,
não um 400 genérico do Discord.
"""

from kryncord.interactions.component import ModalFields, valores_de_select
from kryncord.interactions.response import InteractionContext, InteractionState

__all__ = [
    "InteractionContext",
    "InteractionState",
    "ModalFields",
    "valores_de_select",
]
