"""Permissões de membro, cargo e comando.

Permissões são bits, o mesmo formato dos intents — e a mesma razão para
serem contrato de protocolo: os valores vêm do Discord e mudar um deles
não quebra o import, quebra silenciosamente a autorização do bot.

Este módulo existe separado de `enums.py` porque `Permissions` não é um
enum simples: ele tem parse (aceitar nome, número ou o próprio flag) e
precisa ser importado por `models/role.py`, por `config.py` e pela
validação de comandos. Três donos, um módulo só.

`default_member_permissions` aceita qualquer uma das três formas porque
o usuário que escreve no decorator já pensa em "MANAGE_GUILD", não em
``1 << 5``.
"""

from __future__ import annotations

from enum import IntFlag

from kryncord.errors import DefinitionError


class Permissions(IntFlag):
    """Bits de permissão, conforme a documentação oficial do Discord."""

    # --- gerenciamento do servidor ---
    CREATE_INSTANT_INVITE = 1 << 0
    KICK_MEMBERS = 1 << 1
    BAN_MEMBERS = 1 << 2
    ADMINISTRATOR = 1 << 3
    MANAGE_CHANNELS = 1 << 4
    MANAGE_GUILD = 1 << 5
    ADD_REACTIONS = 1 << 6
    VIEW_AUDIT_LOG = 1 << 7
    PRIORITY_SPEAKER = 1 << 8
    STREAM = 1 << 9

    # --- canais de voz ---
    VIEW_CHANNEL = 1 << 10
    SEND_MESSAGES = 1 << 11
    SEND_TTS_MESSAGES = 1 << 12
    MANAGE_MESSAGES = 1 << 13
    EMBED_LINKS = 1 << 14
    ATTACH_FILES = 1 << 15
    READ_MESSAGE_HISTORY = 1 << 16
    MENTION_EVERYONE = 1 << 17
    USE_EXTERNAL_EMOJIS = 1 << 18
    VIEW_GUILD_INSIGHTS = 1 << 19
    CONNECT = 1 << 20
    SPEAK = 1 << 21
    MUTE_MEMBERS = 1 << 22
    DEAFEN_MEMBERS = 1 << 23
    MOVE_MEMBERS = 1 << 24
    USE_VAD = 1 << 25

    # --- moderação e mais ---
    CHANGE_NICKNAME = 1 << 26
    MANAGE_NICKNAMES = 1 << 27
    MANAGE_ROLES = 1 << 28
    MANAGE_WEBHOOKS = 1 << 29
    MANAGE_GUILD_EXPRESSIONS = 1 << 30
    USE_APPLICATION_COMMANDS = 1 << 31
    REQUEST_TO_SPEAK = 1 << 32
    MANAGE_EVENTS = 1 << 33
    MANAGE_THREADS = 1 << 34
    CREATE_PUBLIC_THREADS = 1 << 35
    CREATE_PRIVATE_THREADS = 1 << 36
    USE_EXTERNAL_STICKERS = 1 << 37
    SEND_MESSAGES_IN_THREADS = 1 << 38
    USE_EMBEDDED_ACTIVITIES = 1 << 39
    MODERATE_MEMBERS = 1 << 40

    VIEW_CREATOR_MONETIZATION_ANALYTICS = 1 << 41
    USE_SOUNDBOARD = 1 << 42
    CREATE_GUILD_EXPRESSIONS = 1 << 43
    USE_EXTERNAL_SOUNDS = 1 << 44
    SEND_VOICE_MESSAGES = 1 << 45

    SEND_POLLS = 1 << 49
    USE_EXTERNAL_APPS = 1 << 50

    @classmethod
    def all(cls) -> Permissions:
        """Todas as permissões conhecidas.

        Útil para `default_member_permissions` de comando que só roda
        pra staff — `Permissions.all()` diz "qualquer uma" sem listar.
        """
        value = 0
        for member in cls:
            value |= member.value
        return cls(value)


#: Nomes conhecidos, computados uma vez. Reconstruir a lista em cada
#: erro de parse seria trabalho repetido no pior momento (o usuário já
#: errou, e agora paga um `for` extra).
_NOMES_CONHECIDOS: tuple[str, ...] = tuple(m.name for m in Permissions if m.name is not None)


def parse_permissions(
    value: object,
    *,
    where: str = "permissões",
) -> Permissions:
    """Converte `str`, `Permissions` ou `int` em `Permissions`.

    A regra de `bool` vem **antes** da de `int`: em Python `bool` é
    subclasse de `int`, então `parse_permissions(True)` sem esta checagem
    viraria `ADMINISTRATOR` — que é exatamente o tipo de silêncio que
    transforma um `True` esquecido numa permissão total.

    `where` entra na mensagem de erro, para o chamador saber qual campo
    estava errado.
    """
    # Antes de `int` — ver docstring.
    if isinstance(value, bool):
        raise DefinitionError(
            f"{where}: {value!r} não é uma permissão. Aceito nome "
            f"('MANAGE_GUILD'), número (1 << 5) ou Permissions."
        )

    if isinstance(value, Permissions):
        return value

    if isinstance(value, str):
        return _parse_name(value, where)

    if isinstance(value, int):
        return Permissions(value)

    raise DefinitionError(
        f"{where}: {type(value).__name__} não é uma permissão. Aceito "
        f"nome ('MANAGE_GUILD'), número (1 << 5) ou Permissions."
    )


def _parse_name(name: str, where: str) -> Permissions:
    """Um nome por chamada — `parse_permissions` aceita uma `str` só.

    Sequências ficam por conta do chamador, que passa uma lista e o
    loop do `CommandOptions` resolve. Misturar as duas formas aqui
    faria `parse_permissions("A B")` significar duas coisas.
    """
    alvo = name.strip().upper().replace(" ", "_").replace("-", "_")
    try:
        return Permissions[alvo]
    except KeyError:
        sugestao = _mais_parecido(alvo)
        dica = f" — quis dizer '{sugestao}'?" if sugestao else ""
        raise DefinitionError(f"{where}: permissão desconhecida {name!r}{dica}") from None


def _mais_parecido(alvo: str) -> str | None:
    """Sugestão por proximidade. O mesmo comportamento dos `create_*`.

    Só devolve quando a similaridade é alta — sugerir algo a qualquer
    custo é pior que não sugerir, porque o usuário confia no texto.
    """
    import difflib

    proximos = difflib.get_close_matches(alvo, _NOMES_CONHECIDOS, n=1, cutoff=0.6)
    return proximos[0] if proximos else None


def parse_permissions_list(
    value: object,
    *,
    where: str = "permissões",
) -> Permissions | None:
    """Converte o que `CommandOptions.default_member_permissions` aceita.

    `None` devolve `None` — "sem restrição" é diferente de "nenhuma
    permissão", e fundir os dois faria um comando abrir para todo mundo
    quando o autor quis fechar para staff.
    """
    if value is None:
        return None

    if isinstance(value, (str, Permissions, int)) and not isinstance(value, bool):
        return parse_permissions(value, where=where)

    if isinstance(value, (list, tuple, set, frozenset)):
        combinada = Permissions(0)
        for item in value:
            combinada |= parse_permissions(item, where=where)
        return combinada

    return parse_permissions(value, where=where)
