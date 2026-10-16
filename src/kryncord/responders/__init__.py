"""Roteador declarativo para botões, selects e modais.

Roteia `custom_id` como rota HTTP: `/manage/user/:user_id/:action`. O
roteador compila os padrões e ordena por especificidade — literal
pesa mais que `:param`, que pesa mais que `?:param`, que pesa mais que
`**` (0013).

Atenção: parâmetro extraído de `custom_id` é **dado**, não autorização.
Quem constrói o `custom_id` pode ser qualquer um. Permissão é checagem
do handler.
"""

from kryncord.responders.context import ResponderContext
from kryncord.responders.converters import (
    converte,
    plano_de,
    recebe_params_dict,
    registrar_conversor,
    resolve_conversor,
)
from kryncord.responders.decorators import responder
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
    "Esperas",
    "Match",
    "Padrao",
    "Params",
    "ResponderContext",
    "ResponderEntry",
    "ResponderRegistry",
    "Segmento",
    "block",
    "build_custom_id",
    "compose",
    "conflitam",
    "converte",
    "dispatch_responder",
    "emit_responder",
    "ordena",
    "parse_rota",
    "plano_de",
    "recebe_params_dict",
    "registrar_conversor",
    "resolve_conversor",
    "responder",
]
