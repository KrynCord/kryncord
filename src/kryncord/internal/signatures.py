"""Validação de assinatura de handler — o primeiro parâmetro tipado.

O `0031` decidiu: a classe entregue ao handler é **determinística**,
vinda do decorator/dispatch, nunca da anotação. A anotação então não
escolhe o que chega — ela é o contrato, e contrato que mente tem que
falhar na importação.

Aqui mora essa checagem, num sítio só: comandos, componentes e
autocomplete fazem a mesma pergunta ("o primeiro parâmetro é a classe
que vou entregar?"), e reimplementar em cada um seria três lugares
para a regra divergir.
"""

from __future__ import annotations

import inspect
import types
from typing import Any, Union, get_args, get_origin, get_type_hints

from kryncord.errors import HandlerSignatureError


def primeiro_parametro(fn: Any) -> inspect.Parameter | None:
    """O primeiro parâmetro posicional de `fn`, ou `None`.

    `*args` não conta como primeiro parâmetro — quem escreve
    `async def h(inter, *args)` ainda tem o `inter` declarado.
    """
    try:
        assinatura = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    for parametro in assinatura.parameters.values():
        if parametro.kind in (parametro.POSITIONAL_ONLY, parametro.POSITIONAL_OR_KEYWORD):
            return parametro
    return None


def anotacao_de(fn: Any, nome: str) -> Any:
    """A anotação do parâmetro `nome`, resolvida no escopo do módulo.

    `None` quando não há anotação **ou** quando ela não resolve (forward
    ref solta, import faltando). Estourar `NameError` aqui apontaria para
    a linha do import, não para a linha do decorator — e é o decorator
    que o autor está olhando.
    """
    try:
        return get_type_hints(fn).get(nome)
    except Exception:
        return None


def valida_interacao(fn: Any, esperada: type, onde: str) -> None:
    """`HandlerSignatureError` se o 1º parâmetro não é `esperada` (ou filha).

    Anotação é obrigatória (`0031`): sem ela, o editor e o mypy não
    veem o contrato, e o runtime ficaria o único lugar sabendo o que o
    handler recebe. União é aceita quando **todos** os membros são
    aceitáveis — `CommandInteraction | None` de quem escreve defensivo
    não muda o que é entregue.

    `Any` e protocolo passam: não dá para conferir com `issubclass` —
    `Any` é classe no 3.11+ mas significa "qualquer coisa" (não mente),
    e protocolo é estrutural, não hierárquico. Forward ref não
    resolvida vira `None` em `anotacao_de` e cai no erro de anotação
    ausente. `object` **não** passa: é classe, e classe que não é a
    entregue nem sua filha está dizendo que o handler recebe outra
    coisa.
    """
    parametro = primeiro_parametro(fn)
    if parametro is None:
        raise HandlerSignatureError(
            f"{onde}: handler sem parâmetros — o primeiro é sempre a interação, "
            f"anotada com `{esperada.__name__}`. Escreva "
            f"`async def h(interaction: {esperada.__name__}): ...`"
        )

    anotado = anotacao_de(fn, parametro.name)
    if anotado is None:
        raise HandlerSignatureError(
            f"{onde}: o parâmetro {parametro.name!r} precisa da anotação "
            f"`{esperada.__name__}` — a interação entregue é decidida pelo "
            "registro, e a anotação é o contrato lido pelo editor e pelo mypy. "
            f"Escreva `async def h({parametro.name}: {esperada.__name__}): ...`"
        )
    if not _bate(anotado, esperada):
        raise HandlerSignatureError(
            f"{onde}: o parâmetro {parametro.name!r} anota `{_nome(anotado)}`, "
            f"mas a interação entregue é `{esperada.__name__}` — confira a "
            "anotação do primeiro parâmetro"
        )


def _bate(anotado: Any, esperada: type) -> bool:
    # `Any` é classe no 3.11+, mas o que ele declara é "aceita tudo" —
    # e aceitar tudo não mente sobre o que é entregue.
    if anotado is Any:
        return True
    origem = get_origin(anotado)
    if origem is types.UnionType or origem is Union:
        return all(_bate(membro, esperada) for membro in get_args(anotado))
    if not isinstance(anotado, type):
        return True
    if getattr(anotado, "_is_protocol", False):
        # Protocolo é estrutural: issubclass nele é TypeError fora de
        # runtime_checkable, e acertar por acaso não seria conferir.
        return True
    try:
        return issubclass(anotado, esperada)
    except TypeError:
        return True


def _nome(tipo: Any) -> str:
    return getattr(tipo, "__name__", str(tipo))


__all__ = ["anotacao_de", "primeiro_parametro", "valida_interacao"]
