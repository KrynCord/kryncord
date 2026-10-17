"""Interações recebidas do Discord — a API pública tipada (`0031`).

A separação de papéis:

| Peça | Dono |
|---|---|
| `models.interaction.Interaction` | o payload, dado puro |
| `interactions.response.InteractionContext` | o estado da resposta (interno) |
| `interactions.base.BaseInteraction` e filhas | o que o handler recebe |
| `interactions.component.ModalFields` | os campos do modal submetido |

O estado **não** mora no modelo. `Interaction` é `frozen` (`0003`), e o
mesmo payload pode ser entregue a mais de um contexto durante um
dispatch — guardar a máquina nele seria imutabilidade quebrada por
dentro.

O handler nunca vê o `InteractionContext`: ele vê a interação tipada —
`CommandInteraction`, `ButtonInteraction`, `ModalSubmitInteraction`… —
que delega para o dono do estado. A máquina é o único ponto que decide
se uma resposta pode ser mandada: violar a sequência é
`InvalidInteractionState` nosso, não um 400 genérico do Discord.
"""

from kryncord.interactions.autocomplete import (
    MAX_ESCOLHAS,
    AutocompleteInteraction,
    normalize_choices,
)
from kryncord.interactions.base import BaseInteraction, InteractionBase
from kryncord.interactions.commands import (
    CommandInteraction,
    EntryPointInteraction,
    MessageCommandInteraction,
    OptionsAccessor,
    UserCommandInteraction,
)
from kryncord.interactions.component import ModalFields, valores_de_select
from kryncord.interactions.components import (
    CLASSES,
    ButtonInteraction,
    ChannelSelectInteraction,
    ComponentInteraction,
    MentionableSelectInteraction,
    ModalSubmitInteraction,
    RoleSelectInteraction,
    StringSelectInteraction,
    UserSelectInteraction,
    classe_para,
)
from kryncord.interactions.response import InteractionContext, InteractionState

__all__ = [
    "CLASSES",
    "MAX_ESCOLHAS",
    "AutocompleteInteraction",
    "BaseInteraction",
    "ButtonInteraction",
    "ChannelSelectInteraction",
    "CommandInteraction",
    "ComponentInteraction",
    "EntryPointInteraction",
    "InteractionBase",
    "InteractionContext",
    "InteractionState",
    "MentionableSelectInteraction",
    "MessageCommandInteraction",
    "ModalFields",
    "ModalSubmitInteraction",
    "OptionsAccessor",
    "RoleSelectInteraction",
    "StringSelectInteraction",
    "UserCommandInteraction",
    "UserSelectInteraction",
    "classe_para",
    "normalize_choices",
    "valores_de_select",
]
