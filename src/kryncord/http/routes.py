"""Generalização de rotas em buckets de rate limit.

O Discord agrupa endpoints por *bucket*, identificado pelo header
``X-RateLimit-Bucket``. Mas para achar o bucket certo antes da primeira
resposta, é preciso deduzir qual rota equivale a qual — é o que
`generate_route_data` faz.

Duas ideias, ambas do contrato real da API:

1. **Major parameter** — ``/channels/123/messages`` e
   ``/channels/456/messages`` são o mesmo bucket, mas ``/channels/123``
   e ``/channels/456`` têm cotas separadas. O id de channel/guild/webhook
   é o "major": ele separa *instâncias* do bucket, não o bucket em si.

2. **Rota generalizada** — os ids viram ``:id``, então o mapa
   ``método:rota → bucket hash`` cresce de forma limitada, em vez de uma
   entrada por servidor do mundo.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

#: Rotas de callback de interação não têm cota por bucket — dispara em burst.
BURST_MAJOR = "burst"

#: Major parameter ausente. O bucket vale para toda a conta.
GLOBAL_MAJOR = "global"

#: Epoch do Discord em milissegundos (2015-01-01T00:00:00Z).
DISCORD_EPOCH_MS = 1_420_070_400_000

#: Apagar uma mensagem com mais de 14 dias cai num bucket separado — o
#: Discord trata o endpoint como custoso e concede cota própria.
OLD_MESSAGE_CUTOFF_MS = 14 * 24 * 60 * 60 * 1000

#: Snowflakes têm 17 a 19 dígitos. Sequências menores não são ids.
_SNOWFLAKE_RE = re.compile(r"\d{17,19}")

# Grupos: (1) webhookId/token, (2) channels|guilds|webhooks/<id>.
_MAJOR_RE = re.compile(
    r"(?:^/webhooks/(\d{17,19}/[^/?]+))" r"|(?:^/(?:channels|guilds|webhooks)/(\d{17,19}))"
)
_INTERACTION_CALLBACK_RE = re.compile(r"^/interactions/.+/callback$")


@dataclass(frozen=True, slots=True)
class RouteData:
    """Uma rota decomposta para fins de rate limit."""

    major_parameter: str
    """Instância do bucket: id de channel/guild, ``webhookId/token``, ou
    ``global``. Rotas com majors diferentes têm contadores separados."""

    bucket_route: str
    """Rota com ids generalizados. É a chave estável do mapa
    ``método:rota → hash``."""

    original: str
    """Rota como veio, sem generalização — é a que vai na URL de fato."""

    @property
    def is_burst(self) -> bool:
        """Callback de interação: não deve entrar na fila sequencial."""
        return self.major_parameter == BURST_MAJOR


def generate_route_data(method: str, endpoint: str, *, now_ms: int | None = None) -> RouteData:
    """Decomponha um endpoint nas três partes que o rate limit precisa.

    `endpoint` não contém query nem a base da API — só o caminho, começando
    com ``/``. Ex.: ``/channels/123456789012345678/messages``.

    `now_ms` existe só para teste: a regra de mensagem antiga lida com o
    relógio, e depender dele tornaria o teste frágil.
    """
    # Callback de interação resolve antes de tudo: o Discord exige resposta
    # em ~15s, então ele nunca pode esperar a fila do bucket.
    if _INTERACTION_CALLBACK_RE.match(endpoint):
        return RouteData(
            major_parameter=BURST_MAJOR,
            bucket_route="/interactions/:id/:token/callback",
            original=endpoint,
        )

    major = _extract_major(endpoint)
    bucket = _generalize(endpoint)

    # Mensagens antigas: o DELETE vira bucket próprio. O id da mensagem é o
    # quarto segmento do caminho.
    if method == "DELETE" and bucket.startswith("/channels/:id/messages/:id"):
        message_id = _message_id(endpoint)
        if message_id is not None and _age_ms(message_id, now_ms=now_ms) > OLD_MESSAGE_CUTOFF_MS:
            bucket = f"{bucket}/Delete Old Message"

    return RouteData(major_parameter=major, bucket_route=bucket, original=endpoint)


def snowflake_timestamp_ms(snowflake: int) -> int:
    """Timestamp de criação de um snowflake, em milissegundos desde o epoch."""
    return (snowflake >> 22) + DISCORD_EPOCH_MS


def _extract_major(endpoint: str) -> str:
    match = _MAJOR_RE.match(endpoint)
    if match is None:
        return GLOBAL_MAJOR
    # Grupo 2 (channels/guilds/webhooks) tem prioridade sobre o grupo 1 —
    # o fallback da referência lê na ordem inversa.
    return match.group(2) or match.group(1) or GLOBAL_MAJOR


def _generalize(endpoint: str) -> str:
    # Ordem importa e replica a referência: ids → reactions → token.
    bucket = _SNOWFLAKE_RE.sub(":id", endpoint)
    # count=1 de propósito: sem /g na referência, só o primeiro /reactions/
    # é generalizado. Substituir todos mudaria o bucket de rotas com
    # reações duplicadas.
    bucket = re.sub(r"/reactions/.*", "/reactions/:reaction", bucket, count=1)
    return re.sub(r"/webhooks/:id/[^/?]+", "/webhooks/:id/:token", bucket, count=1)


def _message_id(endpoint: str) -> int | None:
    """Extrai o snowflake da mensagem de ``/channels/:c/messages/:m``."""
    parts = endpoint.split("/")
    # ['', 'channels', '<id>', 'messages', '<id>', ...]
    if len(parts) >= 5 and parts[3] == "messages" and parts[4].isdigit():
        return int(parts[4])
    return None


def _age_ms(snowflake: int, *, now_ms: int | None = None) -> int:
    """Idade de um snowflake em milissegundos."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    return now_ms - snowflake_timestamp_ms(snowflake)
