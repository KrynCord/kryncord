"""Primitivas de parsing e representação, compartilhadas pelos modelos.

Três assuntos, e os três nascem do mesmo fato: a API do Discord não é
consistente o suficiente para confiar nela sem filtro.

**Snowflake é `int`, não `str`.** O JSON manda IDs como string de
dígitos porque JavaScript perde precisão acima de ``2**53``. Python não
tem esse problema, e ``int`` dá comparação, ordenação e aritmética —
tudo que uma string não dá. Para mandar de volta à API, ``str(id)``.

**Timestamp vira `datetime` com fuso.** O Discord manda ISO8601 com
``+00:00``. Devolver ``str`` empurra o parse para o código de quem usa a
biblioteca, e empurrar parse para o usuário é como se fabrica bug de
fuso horário.

**Campo ausente é `None`, e não um default.** ``content: str = ""`` num
`Message` mentiria: mensagem vazia e mensagem sem o campo não são a
mesma coisa. ``None`` é honesto sobre o que o payload disse.

Parsing é **tolerante**: tipo errado vira ausência, com log em DEBUG.
Um payload estranho não pode derrubar o bot — é o mesmo princípio de
`SessionInfo.from_dispatch` estendido ao resto dos modelos. Para os
campos sem os quais o objeto não significa nada (o ``id`` de um
`Message`), `from_payload` devolve `None` em vez de objeto incompleto,
e o dispatcher entrega o payload cru — ver `events/dispatcher.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar

from kryncord.logging import get_logger

log = get_logger("models")

T = TypeVar("T")

#: Base de tempo do Discord: 2015-01-01T00:00:00Z, em milissegundos.
#: Os 22 bits baixos de um snowflake são contador e worker, não tempo —
#: por isso o deslocamento, e por isso o valor em ms.
DISCORD_EPOCH_MS = 1_420_070_400_000

#: CDN de assets (avatares, ícones, emblemas).
CDN_BASE = "https://cdn.discordapp.com"


# --------------------------------------------------------------------------
# Primitivas de leitura
# --------------------------------------------------------------------------


def snowflake(data: Mapping[str, Any], key: str, default: int | None = None) -> int | None:
    """Lê um ID como ``int``. Ausente, malformado ou não-numérico: `default`.

    Aceita tanto a string do JSON quanto um int já convertido — o
    segundo aparece quando o payload passou por outro caminho (cache,
    teste) e não veio do ``json.loads``.
    """
    value = data.get(key)
    if isinstance(value, bool):
        # `bool` é subclasse de `int` em Python. Sem este checar,
        # `{"id": true}` viraria `id == 1`, e o bot perseguiria um
        # usuário que não existe.
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def string(data: Mapping[str, Any], key: str, default: str | None = None) -> str | None:
    """Lê uma string. Aceita ``""`` como valor legítimo — não é ausência."""
    value = data.get(key)
    return value if isinstance(value, str) else default


def integer(data: Mapping[str, Any], key: str, default: int | None = None) -> int | None:
    """Lê um inteiro, sem aceitar ``bool`` pelo mesmo motivo de `snowflake`."""
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def boolean(data: Mapping[str, Any], key: str, default: bool = False) -> bool:
    """Lê um booleano. Ausente: `default` — o Discord omite flags falsas."""
    value = data.get(key)
    return value if isinstance(value, bool) else default


def timestamp(data: Mapping[str, Any], key: str) -> datetime | None:
    """Lê um ISO8601 em ``datetime`` UTC, ou `None` se não parsear.

    ``Z`` e ``+00:00`` são o mesmo instante e viram o mesmo objeto —
    comparar os dois sem normalizar é o bug de data mais comum que
    existe.
    """
    value = data.get(key)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        log.debug("Timestamp irreconhecível em %r: %r", key, value)
        return None
    if parsed.tzinfo is None:
        # O Discord sempre manda fuso; sem ele, assumir UTC é melhor que
        # produzir um datetime que não compara com os outros.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Lê um objeto aninhado. Ausente ou não-objeto: vazio.

    Vazio, e não `None`: quase todo uso é `nested.get("campo")`, e
    obrigar a checagem nula em cada chamada só polui o chamador.
    """
    value = data.get(key)
    return value if isinstance(value, Mapping) else {}


def sequence(data: Mapping[str, Any], key: str) -> tuple[Any, ...]:
    """Lê uma lista como tuple imutável. Ausente ou não-lista: vazio.

    Tuple, e não list: os modelos são `frozen`, e uma lista mutável
    dentro de um objeto imutável é um objeto imutável de mentira.
    """
    value = data.get(key)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return ()
    return tuple(value)


def parse_all(
    data: Mapping[str, Any], key: str, parser: Callable[[Mapping[str, Any]], T | None]
) -> tuple[T, ...]:
    """Parseia uma lista de objetos, descartando o que não deu.

    O Discord manda listas com entradas ruins junto das boas — um
    anexo sem ``id``, uma guild de referência malformada. Derrubar a
    mensagem inteira por causa de uma entrada seria perder um evento
    válido para punir um payload que o bot não pediu.

    Só itens `Mapping` chegam ao parser: o resto nem tenta.
    """
    parsed: list[T] = []
    for item in sequence(data, key):
        if not isinstance(item, Mapping):
            continue
        result = parser(item)
        if result is not None:
            parsed.append(result)
    return tuple(parsed)


# --------------------------------------------------------------------------
# Representação
# --------------------------------------------------------------------------


def snowflake_datetime(value: int) -> datetime:
    """Extrai o instante de criação de um snowflake.

    Todo ID do Discord carrega seu próprio timestamp nos bits altos —
    é assim que dá para saber quando um usuário entrou sem perguntar à
    API.
    """
    milliseconds = (value >> 22) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def cdn(path: str) -> str:
    """Monta uma URL da CDN de assets.

    A CDN não faz parte da API REST e não aceita o token — por isso a
    URL é construída, não buscada.
    """
    return f"{CDN_BASE}/{path}"


def default_avatar_url(index: int) -> str:
    """Avatar genérico de quem não escolheu um.

    O índice é o ``discriminator % 5`` para contas antigas, e o mesmo
    cálculo serve para contas novas (discriminator ``0``).
    """
    return cdn(f"embed/avatars/{index % 5}.png")
