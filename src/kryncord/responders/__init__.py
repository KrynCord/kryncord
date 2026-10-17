"""Roteador declarativo para botões, selects e modais.

Roteia `custom_id` como rota: `/manage/user/{user_id}/{action}` —
literal, `{param}` obrigatório, `{?param}` opcional, `**` curinga no
fim (0013, revisto no `0031`). O roteador compila os padrões e ordena
por especificidade — literal pesa mais que `{param}`, que pesa mais que
`{?param}`, que pesa mais que `**`.

O que o handler recebe é a **interação tipada** (`0031`): a classe vem
do tipo da interação — `@button` entrega `ButtonInteraction`,
`@modal_submit` entrega `ModalSubmitInteraction`, e por diante. Um
objeto genérico "ctx" não existe mais na API pública.

Atenção: parâmetro extraído de `custom_id` é **dado**, não autorização.
Quem constrói o `custom_id` pode ser qualquer um. Permissão é checagem
do handler.
"""

from kryncord.interactions.components import (
    ButtonInteraction,
    ChannelSelectInteraction,
    ComponentInteraction,
    MentionableSelectInteraction,
    ModalSubmitInteraction,
    RoleSelectInteraction,
    StringSelectInteraction,
    UserSelectInteraction,
)
from kryncord.responders.converters import (
    converte,
    plano_de,
    recebe_params_dict,
    registrar_conversor,
    resolve_conversor,
)
from kryncord.responders.decorators import (
    button,
    channel_select,
    mentionable_select,
    modal_submit,
    responder,
    role_select,
    string_select,
    user_select,
)
from kryncord.responders.dispatch import (
    Esperas,
    block,
    compose,
    dispatch_responder,
    emit_responder,
)
from kryncord.responders.ids import (
    MAX_CUSTOM_ID,
    Segmento,
    build_custom_id,
    parse_rota,
)
from kryncord.responders.params import Params
from kryncord.responders.patterns import Padrao, conflitam, ordena
from kryncord.responders.registry import Match, ResponderEntry, ResponderRegistry

__all__ = [
    "MAX_CUSTOM_ID",
    "ButtonInteraction",
    "ChannelSelectInteraction",
    "ComponentInteraction",
    "Esperas",
    "Match",
    "MentionableSelectInteraction",
    "ModalSubmitInteraction",
    "Padrao",
    "Params",
    "ResponderEntry",
    "ResponderRegistry",
    "RoleSelectInteraction",
    "Segmento",
    "StringSelectInteraction",
    "UserSelectInteraction",
    "block",
    "build_custom_id",
    "button",
    "channel_select",
    "compose",
    "conflitam",
    "converte",
    "dispatch_responder",
    "emit_responder",
    "mentionable_select",
    "modal_submit",
    "ordena",
    "parse_rota",
    "plano_de",
    "recebe_params_dict",
    "registrar_conversor",
    "resolve_conversor",
    "responder",
    "role_select",
    "string_select",
    "user_select",
]
