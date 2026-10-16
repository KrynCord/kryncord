"""Tipos de entidade do cache e as chaves que as identificam.

A chave é **string**, não `tuple`. `protocol.py` promete uma interface
que outras implementações vão cumprir, e uma tupla `(guild, user)` só
faz sentido dentro de um dict em memória — no Redis viraria algo que
tem que ser serializado de um jeito nosso. `f"{guild}:{user}"` atravessa
qualquer backend sem tradução.

A separação é `:` porque é o único caractere que não aparece num
snowflake nem num nome de canal. Quem lê a chave consegue dizer de qual
guild ela fala, o que importa quando alguém abre um debugger.

`member`, `role` e `voice_state` carregam a guild na chave porque são
os únicos que não são globais: o mesmo ID de usuário é membro de cinco
servidores, e são cinco entradas diferentes. `user`, `guild` e `channel`
têm ID global — o Discord não reusa — então a guild não entra.

O `group` (a guild de origem) existe para enumeração: sem ele,
"membros desta guild" seria uma varredura em todas as chaves de membro
de todos os servidores. Com ele, é um lookup direto. É o preço de
`members_of()` custar o que custa.
"""

from __future__ import annotations

from enum import StrEnum


class CacheKind(StrEnum):
    """Os sete tipos de entidade que o cache guarda.

    `StrEnum` de propósito: o valor já é a string usada na chave e num
    log, então `str(CacheKind.GUILD)` e `"guild"` não podem divergir.
    """

    GUILD = "guild"
    CHANNEL = "channel"
    USER = "user"
    MEMBER = "member"
    ROLE = "role"
    MESSAGE = "message"
    VOICE_STATE = "voice_state"


def guild_key(guild_id: int | str) -> str:
    """Chave de um servidor."""
    return str(guild_id)


def channel_key(channel_id: int | str) -> str:
    """Chave de um canal — ID global, sem guild na chave."""
    return str(channel_id)


def user_key(user_id: int | str) -> str:
    """Chave de uma conta — ID global, sem guild na chave."""
    return str(user_id)


def message_key(message_id: int | str) -> str:
    """Chave de uma mensagem — ID global."""
    return str(message_id)


def member_key(guild_id: int | str, user_id: int | str) -> str:
    """Chave de um membro **dentro** de uma guild.

    Mesmo usuário em dois servidores são duas chaves: `Member` não é a
    conta, é a presença dela num lugar específico — apelido, cargos e
    data de entrada mudam por servidor.
    """
    return f"{guild_id}:{user_id}"


def role_key(guild_id: int | str, role_id: int | str) -> str:
    """Chave de um cargo — só existe dentro de uma guild."""
    return f"{guild_id}:{role_id}"


def voice_state_key(guild_id: int | str, user_id: int | str) -> str:
    """Chave de um estado de voz — um usuário dentro de um guild.

    Mesmo formato do `member_key`, e pelo mesmo motivo: a mesma pessoa
    pode estar no canal de voz do servidor A e fora do do B, e são duas
    entradas. Além disso é o que torna `voice_state_update -> (old, new)`
    possível — `0025` §6.
    """
    return f"{guild_id}:{user_id}"


def guild_group(guild_id: int | str) -> str:
    """Agrupamento de tudo que pertence a uma guild.

    Não é uma chave de entidade: é o rótulo que `CacheProtocol.set`
    guarda junto para depois devolver `group_values` sem varrer tudo.
    """
    return str(guild_id)
