"""Entrega eventos do Gateway para o código da aplicação.

O dispatcher define se handlers rodam em sequência ou em tarefas
independentes. A política é documentada e testada, inclusive para
exceção e cancelamento — handler que derruba o bot porque alguém
esqueceu um `await` é o tipo de falha que tem que ser decidida, não
acidental.

O `@event` vive em `decorators.py` e valida a aridade na importação;
o `client.on` vive em `client.py` e valida em runtime. São dois caminhos
para a mesma tabela — `EVENT_PAYLOADS`, em `payloads.py` —, e a
diferença entre eles é o `EventContext` que só o decorator entrega.

Ver `events/dispatcher.py` para a política de execução escolhida e o
porquê, e `events/payloads.py` para a tabela que decide o que o
handler recebe.
"""

from kryncord.events.context import EventContext
from kryncord.events.decorators import event
from kryncord.events.dispatcher import (
    REGISTRY,
    ErrorHandler,
    EventDispatcher,
    EventEntry,
    EventHandler,
    EventMiddleware,
    Parser,
)
from kryncord.events.names import RAW_TO_SNAKE, EventName, normalize_event_name
from kryncord.events.payloads import (
    EVENT_PAYLOADS,
    EVENTOS_COM_OLD,
    PayloadShape,
    forma_de,
    monta_args,
)
from kryncord.events.snapshot import instantanea

__all__ = [
    "EVENTOS_COM_OLD",
    "EVENT_PAYLOADS",
    "RAW_TO_SNAKE",
    "REGISTRY",
    "ErrorHandler",
    "EventContext",
    "EventDispatcher",
    "EventEntry",
    "EventHandler",
    "EventMiddleware",
    "EventName",
    "Parser",
    "PayloadShape",
    "event",
    "forma_de",
    "instantanea",
    "monta_args",
    "normalize_event_name",
]
