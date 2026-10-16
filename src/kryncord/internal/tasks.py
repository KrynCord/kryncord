"""`spawn` — disparar trabalho em background **com dono**.

O `0012` colocou o `spawn` nos três contextos com uma exigência do
conselho (07 Concorrência): task órfã no `Client` não tem dono, e o
cancelamento no shutdown tem que alcançar tudo que foi disparado.

Um `asyncio.create_task` cru não alcança: a referência se perde e a
task sobrevive ao client. O `TaskRegistry` segura a referência e
cancela no fim — é o mesmo padrão do `asyncio.TaskGroup`, sem o
cancelamento do pai quando um filho falha (aqui filho falhando é
logado, não propagado; handler de fundo que derruba o bot inteiro é
o oposto do que "background" promete).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from kryncord.logging import get_logger

_log = get_logger(__name__)


class TaskRegistry:
    """Tasks com dono — nasce no `Client`, morre no `aclose`."""

    __slots__ = ("_tasks",)

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def spawn(self, coro: Coroutine[Any, Any, Any], *, nome: str = "") -> asyncio.Task[Any]:
        """Cria a task e segura a referência.

        A referência forte é o que o `asyncio` pede: task sem
        referência pode ser coletada no meio da execução — o bug mais
        silencioso que existe, porque só acontece sob pressão de GC.
        """
        task = asyncio.create_task(coro, name=nome or None)
        self._tasks.add(task)
        task.add_done_callback(self._terminou)
        return task

    def _terminou(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            #: Handler de fundo quebrando não derruba o bot — mas
            #: engolir sem log seria a task que ninguém nunca descobre.
            _log.error("task de fundo falhou: %r", exc, exc_info=exc)

    @property
    def vivas(self) -> int:
        return len(self._tasks)

    async def cancela_todas(self) -> None:
        """Cancela e espera — o `aclose` do `Client` chama no fim."""
        pendentes = [t for t in self._tasks if not t.done()]
        for task in pendentes:
            task.cancel()
        if pendentes:
            await asyncio.gather(*pendentes, return_exceptions=True)
        self._tasks.clear()
