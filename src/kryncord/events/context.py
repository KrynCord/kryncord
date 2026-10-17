"""`EventFrame` — o quadro interno de um dispatch de evento.

O handler **não** vê este objeto (`0031`): `client.on` e `@event`
recebem o payload só, um caminho para os dois. O quadro mora onde o
payload não basta — a middleware (`fn(frame, block)`) e o `on_error`
(`fn(frame, exc)`), que precisam do nome do evento, do client e do
espaço compartilhado, e que são mecanismos internos, não a superfície
que o autor do bot escreve contra.

Não está em `__all__` de `kryncord.events` de propósito: não é API
pública, e exportá-lo recriaria o "contexto na frente do payload" que
a migração acabou de remover.

## `args` é `list` e é mutável de propósito

Middleware pode **injetar** argumento: escrever `frame.args[0] = outro`
muda o que os handlers recebem no modo `sequential`. A ideia 10 §6 traz
esse recurso do TypeScript e ele só funciona com lista viva — tupla
imutável faria a injeção falhar em silêncio.

No modo `concurrent` cada handler lê a lista uma vez, e a mutação
daqui para frente alcança só quem ainda não rodou. Não é bug, é o
contrato do `sequential` ser o default: quem escolhe concorrência já
escolheu que a ordem entre handlers não é garantida.

## `state` é por dispatch, não por quadro

O `0012` diz "criado por dispatch". Um `INTERACTION_CREATE` alimenta o
roteamento de interação **e** os handlers de `@event("interaction_create")`,
e os dois frames são objetos diferentes — o dicionário é que é o
mesmo. Nasce vazio, morre no fim do despacho.
"""

from __future__ import annotations

from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any

from kryncord.events.names import normalize_event_name

if TYPE_CHECKING:
    from kryncord.client import Client
    from kryncord.internal.tasks import TaskRegistry


class EventFrame:
    """O evento em si: qual, com o quê, e para quem."""

    __slots__ = ("_args", "_client", "_name", "_state", "_tasks")

    def __init__(
        self,
        name: str,
        args: list[Any] | None = None,
        *,
        client: Client | None = None,
        state: dict[str, Any] | None = None,
        tasks: TaskRegistry | None = None,
    ) -> None:
        self._name = normalize_event_name(name)
        #: Mutável por decisão — ver o docstring do módulo. Copiar aqui
        #: seria perder a injeção de argumentos do `0012`/ideia 10 §6.
        self._args: list[Any] = list(args) if args is not None else []
        self._client = client
        #: Por dispatch, compartilhado com middleware. Não vaza entre
        #: dois despachos — nasce vazio a cada um (0012).
        self._state: dict[str, Any] = state if state is not None else {}
        self._tasks = tasks

    # ------------------------------------------------------------------
    # O evento
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """O nome em ``snake_case``, como o Discord manda normalizado.

        `client.on("READY")` e `@event("ready")` veem o mesmo valor —
        a forma vinda do gateway é a de sempre, a normalizada é esta.
        """
        return self._name

    @property
    def args(self) -> list[Any]:
        """Os argumentos do evento, mutável.

        Quem lê, lê isto; quem escreve, escreve aqui. O despacho
        desempacota **a lista viva** a cada handler, que é o que faz a
        mutação ter efeito.
        """
        return self._args

    @property
    def client(self) -> Client | None:
        """O `Client`, ou `None` em quadro montado à mão.

        `None` existe porque o `EventFrame` é construído pelo
        dispatcher, e o dispatcher é construído pelo `Client` — passar
        o client por aqui seria um ciclo em tempo de importação que não
        ganha nada.
        """
        return self._client

    @property
    def state(self) -> dict[str, Any]:
        """Espaço por dispatch, compartilhado com as middlewares.

        Uma middleware escreve `frame.state["x"]`. Com o
        `INTERACTION_CREATE`, o mesmo dicionário chega ao contexto do
        comando ou do responder que o roteamento construiu — é o
        único caso em que dois objetos diferentes carregam o mesmo
        estado, e é justamente porque é um dispatch só.
        """
        return self._state

    # ------------------------------------------------------------------
    # Trabalho de fundo
    # ------------------------------------------------------------------

    def spawn(self, coro: Coroutine[Any, Any, Any], *, nome: str = "") -> Any:
        """Dispara corrotina em background **com dono**.

        A task entra no `TaskRegistry` do client — cancelada no shutdown,
        não órfã. Sem registry não há spawn (0012, parecer do 07): task
        sem dono sobrevive ao client, e é o oposto do que "background"
        promete.

        É também o que substitui o "o dispatcher não espera" da ideia
        10 §5 — quem quer paralelismo sem esperar chama `frame.spawn` e
        devolve.
        """
        tasks = self._tasks or getattr(self._client, "_tasks", None)
        if tasks is None:
            raise RuntimeError(
                "spawn() precisa de um TaskRegistry — o Client fornece um no boot. "
                "Quadro montado à mão em teste: passe tasks=TaskRegistry()."
            )
        return tasks.spawn(coro, nome=nome)

    def __repr__(self) -> str:
        """O que importa ao inspecionar: qual evento, e com quantos args."""
        return f"{type(self).__name__}({self._name!r}, args={len(self._args)})"
