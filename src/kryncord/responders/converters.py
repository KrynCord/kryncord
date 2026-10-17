"""Conversão por anotação — o `{user_id}` cru vira `int`, `User`, `datetime`.

A anotação **é** o conversor. No TS tudo é string e você chama `parse`
à mão; em Python a anotação já existe, o mypy já a lê, e duplicar isso
numa string mágica seria criar o typo que nenhuma checagem pega.

A assinatura é ``fn(raw, inter) -> T`` — sempre os dois. O `inter` é a
interação tipada (`ButtonInteraction`, `ModalSubmitInteraction`…), que
já tem `.client` e `.state`; conversores simples ignoram o segundo
argumento. Um objeto a mais de "contexto de conversão" seria um terceiro
contexto para aprender (0014).

Síncrono e assíncrono são aceitos, e **síncrono não é embrulhado**:
`await` por parâmetro por invocação é o custo que a disciplina síncrona
existe para evitar. O dispatcher decide com `iscoroutinefunction`.
"""

from __future__ import annotations

import functools
import inspect
import types
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, TypeVar, Union, cast, get_args, get_origin, get_type_hints
from uuid import UUID

from kryncord.errors import ConversionError, ResponderDefinitionError
from kryncord.models.channel import Channel
from kryncord.models.interaction import Interaction
from kryncord.models.member import Member
from kryncord.models.message import Message
from kryncord.models.role import Role
from kryncord.models.user import User

T = TypeVar("T")


# ----------------------------------------------------------------------
# Conversores base — cada um é `fn(raw, ctx)`
# ----------------------------------------------------------------------


def _de_int(raw: str, ctx: Any) -> int:
    try:
        return int(raw)
    except ValueError:
        raise ConversionError(f"{raw!r} não é int") from None


def _de_float(raw: str, ctx: Any) -> float:
    try:
        return float(raw)
    except ValueError:
        raise ConversionError(f"{raw!r} não é float") from None


def _de_bool(raw: str, ctx: Any) -> bool:
    """`"true"/"1"/"yes"` → True; o resto → False.

    É a tabela da ideia 08 §2. Recusar "yes" com erro seria impor uma
    opinião a um valor que a gente mesmo construiu.
    """
    return raw.strip().lower() in ("true", "1", "yes")


def _de_datetime(raw: str, ctx: Any) -> datetime:
    """ISO, epoch em segundos ou epoch em milissegundos — pelo formato.

    ```
    valor.isdigit() e len == 10  -> epoch em segundos
    valor.isdigit() e len == 13  -> epoch em milissegundos
    senão                         -> datetime.fromisoformat
    ```

    Uma linha cobre os dois formatos reais, e ISO nunca colide porque
    sempre tem `-` ou `:` — `isdigit()` não casa.
    """
    if raw.isdigit() and len(raw) == 10:
        return datetime.fromtimestamp(int(raw))
    if raw.isdigit() and len(raw) == 13:
        return datetime.fromtimestamp(int(raw) / 1000)
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise ConversionError(
            f"{raw!r} não é datetime — ISO, epoch s (10 dígitos) ou ms (13)"
        ) from None


def _de_uuid(raw: str, ctx: Any) -> UUID:
    try:
        return UUID(raw)
    except ValueError:
        raise ConversionError(f"{raw!r} não é UUID") from None


# ----------------------------------------------------------------------
# Conversores do Discord: cache -> REST -> erro (0014)
# ----------------------------------------------------------------------


def _id_de(raw: str, nome: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise ConversionError(f"{nome} espera snowflake, veio {raw!r}") from None


async def _de_user(raw: str, ctx: Any) -> User:
    identificador = _id_de(raw, "User")
    cache = getattr(ctx, "cache", None)
    if cache is not None:
        achado = cache.get_user(identificador)
        if achado is not None:
            return cast("User", achado)
    client = getattr(ctx, "client", None)
    if client is not None:
        try:
            return cast("User", await client.api.users.fetch(identificador))
        except Exception as exc:
            raise ConversionError(f"User {raw!r} não resolvido: {exc}") from exc
    raise ConversionError(f"User {raw!r} fora do cache e sem client para buscar")


async def _de_member(raw: str, ctx: Any) -> Member:
    """`Member` precisa de guild — e ela vem do contexto, não do modelo.

    `Member` não tem `guild_id` (0008, verificado ao vivo): quem sabe
    em que guild ele está é quem leu o evento.
    """
    interacao: Interaction | None = getattr(ctx, "interaction", None)
    guild_id = interacao.guild_id if interacao is not None else None
    if guild_id is None:
        raise ConversionError(
            f"Member {raw!r} exige guild — interação fora de guild não tem membro"
        )
    identificador = _id_de(raw, "Member")
    cache = getattr(ctx, "cache", None)
    if cache is not None:
        achado = cache.get_member(guild_id, identificador)
        if achado is not None:
            return cast("Member", achado)
    client = getattr(ctx, "client", None)
    if client is not None:
        try:
            return cast("Member", await client.api.members.fetch(guild_id, identificador))
        except Exception as exc:
            raise ConversionError(f"Member {raw!r} não resolvido: {exc}") from exc
    raise ConversionError(f"Member {raw!r} fora do cache e sem client para buscar")


async def _de_channel(raw: str, ctx: Any) -> Channel:
    identificador = _id_de(raw, "Channel")
    cache = getattr(ctx, "cache", None)
    if cache is not None:
        achado = cache.get_channel(identificador)
        if achado is not None:
            return cast("Channel", achado)
    client = getattr(ctx, "client", None)
    if client is not None:
        try:
            return cast("Channel", await client.api.channels.fetch(identificador))
        except Exception as exc:
            raise ConversionError(f"Channel {raw!r} não resolvido: {exc}") from exc
    raise ConversionError(f"Channel {raw!r} fora do cache e sem client para buscar")


async def _de_role(raw: str, ctx: Any) -> Role:
    """`Role` é cache-then-REST também — a rota de role por id existe."""
    interacao: Interaction | None = getattr(ctx, "interaction", None)
    guild_id = interacao.guild_id if interacao is not None else None
    if guild_id is None:
        raise ConversionError(f"Role {raw!r} exige guild — cargo fora de guild não existe")
    identificador = _id_de(raw, "Role")
    cache = getattr(ctx, "cache", None)
    if cache is not None:
        achado = cache.get_role(guild_id, identificador)
        if achado is not None:
            return cast("Role", achado)
    client = getattr(ctx, "client", None)
    if client is not None:
        try:
            return cast("Role", await client.api.roles.fetch(guild_id, identificador))
        except Exception as exc:
            raise ConversionError(f"Role {raw!r} não resolvido: {exc}") from exc
    raise ConversionError(f"Role {raw!r} fora do cache e sem client para buscar")


def _de_message(raw: str, ctx: Any) -> Message:
    """`Message` é **só cache** — e é escolha, não omissão.

    Buscar mensagem por REST exige o `channel_id`, e o `custom_id` não o
    tem. Inventar um "channel implícito" seria adivinhar; a mensagem que
    importa num botão é a que está no cache da conexão.
    """
    identificador = _id_de(raw, "Message")
    cache = getattr(ctx, "cache", None)
    if cache is not None:
        achado = cache.get_message(identificador)
        if achado is not None:
            return cast("Message", achado)
    raise ConversionError(
        f"Message {raw!r} fora do cache — mensagem por REST exige channel_id, "
        f"que o custom_id não carrega. Se precisa dela fora do cache, guarde o "
        f"que importa em outro param."
    )


# ----------------------------------------------------------------------
# Tabela e registro
# ----------------------------------------------------------------------

_BASE: dict[Any, Any] = {
    int: _de_int,
    float: _de_float,
    bool: _de_bool,
    datetime: _de_datetime,
    UUID: _de_uuid,
    User: _de_user,
    Member: _de_member,
    Channel: _de_channel,
    Role: _de_role,
    Message: _de_message,
}

#: Conversores customizados, por tipo. Registrar é estender sem fork.
_CUSTOM: dict[Any, Any] = {}


def registrar_conversor(tipo: Any, conversor: Any) -> None:
    """Registra um conversor para uma anotação própria.

    O conversor é ``fn(raw, ctx)`` — síncrono ou assíncrono, o
    dispatcher decide. Sobrescrever um existente é erro: dois módulos
    brigando pelo mesmo tipo é o bug que só aparece em runtime.
    """
    if tipo in _BASE or tipo in _CUSTOM:
        raise ResponderDefinitionError(
            f"já existe conversor para {getattr(tipo, '__name__', tipo)!r} — "
            f"sobrescrever em silêncio faria os dois módulos brigarem em runtime"
        )
    _CUSTOM[tipo] = conversor


@functools.lru_cache(maxsize=512)
def resolve_conversor(anotacao: Any) -> tuple[Any, bool]:
    """`(conversor, opcional)` para uma anotação.

    `conversor=None` é identidade — string crua passa. `opcional=True`
    é a anotação `T | None`, que o 0013 trata como o mesmo sinal do
    `{?x}` na rota.

    Anotação desconhecida é erro **aqui**, na importação, com o nome
    da anotação na mensagem — não no clique, com um `TypeError` que
    não diz qual dos cinco params era.
    """
    if anotacao is None or anotacao is str or anotacao is Any:
        return None, False

    if anotacao in _BASE:
        return _BASE[anotacao], False
    if anotacao in _CUSTOM:
        return _CUSTOM[anotacao], False

    origem = get_origin(anotacao)
    if origem is Literal:
        return _literal(anotacao), False

    #: `X | Y` moderno cria `types.UnionType`; só `Optional[X]` do
    #: typing cria `typing.Union`. Os dois chegam aqui e são a mesma
    #: pergunta — aceitar um só quebraria a forma que todo mundo escreve.
    if origem is Union or origem is types.UnionType:
        return _union(anotacao)

    if isinstance(anotacao, type) and issubclass(anotacao, StrEnum):
        return _de_strenum(anotacao), False

    nome = getattr(anotacao, "__name__", repr(anotacao))
    raise ResponderDefinitionError(
        f"anotação {nome!r} não tem conversor — registre um com "
        f"kryncord.registrar_conversor({nome}, fn) ou anote str"
    )


def _literal(anotacao: Any) -> Any:
    """`Literal["a", "b"]` valida contra o conjunto."""
    permitidos = frozenset(get_args(anotacao))

    def conversor(raw: str, ctx: Any) -> str:
        if raw not in permitidos:
            raise ConversionError(f"{raw!r} fora do Literal — permitidos: {sorted(permitidos)}")
        return raw

    return conversor


def _union(anotacao: Any) -> tuple[Any, bool]:
    """`T | None` resolve `T` e marca opcional.

    `T | U` sem `None` não é opcional e não tem um conversor só — é
    erro na importação, porque em runtime seria adivinhar.
    """
    args = get_args(anotacao)
    nao_none = [a for a in args if a is not type(None)]
    if len(args) != 2 or len(nao_none) != 1:
        nomes = [getattr(a, "__name__", repr(a)) for a in args]
        raise ResponderDefinitionError(
            f"anotação union {nomes!r} não suportada — use `T | None` (opcional) "
            f"ou um tipo só. Union de dois tipos não tem conversor único."
        )
    conversor, _ = resolve_conversor(nao_none[0])
    return conversor, True


def _de_strenum(tipo: Any) -> Any:
    def conversor(raw: str, ctx: Any) -> Any:
        try:
            return tipo(raw)
        except ValueError:
            permitidos = [m.value for m in tipo]
            raise ConversionError(
                f"{raw!r} fora do {tipo.__name__} — permitidos: {permitidos}"
            ) from None

    return conversor


async def converte(conversor: Any, raw: str, ctx: Any, nome: str) -> Any:
    """Chama o conversor, síncrono ou assíncrono, sem embrulhar.

    `nome` só entra na mensagem de erro — sem ele, o `ConversionError`
    diria o valor mas não qual dos cinco params quebrou.
    """
    try:
        if conversor is None:
            return raw
        if inspect.iscoroutinefunction(conversor):
            return await conversor(raw, ctx)
        return conversor(raw, ctx)
    except ConversionError as exc:
        raise ConversionError(f"param {nome!r}: {exc}") from exc


# ----------------------------------------------------------------------
# Hints com cache — o hot path do roteador (0014)
# ----------------------------------------------------------------------


@functools.lru_cache(maxsize=512)
def hints_de(fn: Any) -> dict[str, Any]:
    """Anotações do handler, resolvidas **uma vez por função**.

    As funções vivem para sempre no registry (registram na importação),
    então não há fuga de id. Se um `unregister` existir amanhã, este
    cache precisa de limpeza — restrição registrada na 0014.
    """
    try:
        return get_type_hints(fn)
    except Exception:
        return {}


# ----------------------------------------------------------------------
# Plano de injeção — validado na importação, executado no clique
# ----------------------------------------------------------------------

#: `(nome, conversor, opcional, tem_default)` por param injetado.
ItemPlano = tuple[str, Any, bool, bool]

_EMPTY: tuple[ItemPlano, ...] = ()


def assinatura_padrao(fn: Any) -> list[inspect.Parameter]:
    """Os params depois do primeiro — o primeiro é o `ctx`.

    Erro se não houver primeiro: handler de responder sempre recebe o
    contexto, e handler sem argumento nenhum é handler de evento.
    """
    parametros = list(inspect.signature(fn).parameters.values())
    if not parametros:
        raise ResponderDefinitionError(
            "handler precisa receber o contexto — fn(ctx, ...). Handler sem "
            "parâmetro nenhum é handler de evento, não de responder."
        )
    return parametros[1:]


def _e_variadic(fn: Any) -> bool:
    """`*args`/`**kwargs` é o pedido explícito de "me dá tudo" (K9)."""
    return any(
        p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        for p in assinatura_padrao(fn)
    )


@functools.lru_cache(maxsize=512)
def _nomes_de_rota(rota: str) -> frozenset[str]:
    from kryncord.responders.ids import parse_rota

    #: `s.nomes` cobre param puro, `{?x}` e misto (`produto:{id}`) de
    #: uma vez — a forma antiga (`s.e_param or wildcard`) perdia o
    #: embutido.
    return frozenset(nome for s in parse_rota(rota) for nome in s.nomes)


@functools.lru_cache(maxsize=512)
def _e_opcional_na_rota(rota: str, nome: str) -> bool:
    from kryncord.responders.ids import parse_rota

    return any(nome in s.opcionais for s in parse_rota(rota))


@functools.lru_cache(maxsize=512)
def recebe_params_dict(fn: Any, rota: str) -> bool:
    """Se o handler quer o dict cru em vez dos params nomeados.

    A regra: parâmetro chamado `params` que **não** é param da rota.
    Se a rota tem um param com esse nome, ele é param — o valor
    concreto vence, e o dict não é injetado.
    """
    if "params" in _nomes_de_rota(rota):
        return False
    if _e_variadic(fn):
        return False
    return any(p.name == "params" for p in assinatura_padrao(fn))


@functools.lru_cache(maxsize=512)
def plano_de(fn: Any, rota: str) -> tuple[ItemPlano, ...]:
    """O que o dispatcher injeta neste handler — validado **agora**.

    Toda a checagem que dá para fazer sem um clique acontece aqui, na
    importação: param que a rota não fornece, anotação sem conversor.
    No clique, o mesmo erro seria um `TypeError` que não diz qual dos
    cinco params era.

    - ``fn(ctx)`` → plano vazio;
    - ``fn(ctx, *args)`` → plano vazio, validação pulada (K9);
    - ``fn(ctx, user_id: int)`` → injeta convertido;
    - ``fn(ctx, params)`` → o dict cru, injetado pelo dispatcher à
      parte; o item sai do plano para não passar duas vezes.

    Opcional é a **união** dos dois sinais: `{?x}` na rota ou `| None`
    na anotação. Os exemplos da 0013 usam cada forma de um jeito, e
    recusar a combinação seria recusar o código mais natural.
    """
    padrao_nomes = _nomes_de_rota(rota)
    parametros = assinatura_padrao(fn)

    if _e_variadic(fn):
        return _EMPTY

    dict_form = recebe_params_dict(fn, rota)
    hints = hints_de(fn)
    plano: list[ItemPlano] = []

    for p in parametros:
        if dict_form and p.name == "params":
            continue

        if p.name not in padrao_nomes and p.default is inspect.Parameter.empty:
            raise ResponderDefinitionError(
                f"handler de {rota!r} pede {p.name!r}, que a rota não fornece — "
                f"params da rota: {sorted(padrao_nomes)}. Nome digitado errado?"
            )

        conversor, opcional_anotacao = resolve_conversor(hints.get(p.name))
        opcional = opcional_anotacao or _e_opcional_na_rota(rota, p.name)
        tem_default = p.default is not inspect.Parameter.empty
        plano.append((p.name, conversor, opcional, tem_default))

    return tuple(plano)


__all__ = [
    "converte",
    "hints_de",
    "plano_de",
    "recebe_params_dict",
    "registrar_conversor",
    "resolve_conversor",
]
