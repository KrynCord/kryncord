"""Conexão persistente de eventos em tempo real.

Gerencia WebSocket, Identify, heartbeat, ACK, resume e reconexão. Não
sabe nada sobre comandos ou interações — só entrega payloads brutos do
dispatch para o `events/`.

Os exports de aqui embaixo são **internos**: o `Client` público é o
`kryncord.Client`, de outro pacote. Quem importar daqui está mexendo na
engrenagem, não na API.
"""

from kryncord.gateway.client import (
    DEFAULT_GATEWAY_URL,
    EventHandler,
    GatewayClient,
    GatewayStatus,
)
from kryncord.gateway.compression import (
    CompressionMode,
    FrameDecoder,
    build_gateway_url,
)
from kryncord.gateway.connection import (
    GatewaySendRateLimit,
    GatewayTransport,
    WebSocketConnection,
)
from kryncord.gateway.heartbeat import Heartbeat, HeartbeatState
from kryncord.gateway.identify import (
    IdentifyProperties,
    IdentifyThrottler,
    build_identify,
    build_resume,
)
from kryncord.gateway.payloads import Payload, make_heartbeat
from kryncord.gateway.reconnect import (
    CloseDecision,
    ReconnectPolicy,
    Recovery,
    classify_close,
)
from kryncord.gateway.session import InMemorySessionStore, SessionInfo, SessionStore

__all__ = [
    "DEFAULT_GATEWAY_URL",
    "CloseDecision",
    "CompressionMode",
    "EventHandler",
    "FrameDecoder",
    "GatewayClient",
    "GatewaySendRateLimit",
    "GatewayStatus",
    "GatewayTransport",
    "Heartbeat",
    "HeartbeatState",
    "IdentifyProperties",
    "IdentifyThrottler",
    "InMemorySessionStore",
    "Payload",
    "ReconnectPolicy",
    "Recovery",
    "SessionInfo",
    "SessionStore",
    "WebSocketConnection",
    "build_gateway_url",
    "build_identify",
    "build_resume",
    "classify_close",
    "make_heartbeat",
]
