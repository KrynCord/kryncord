"""Ciclo de vida: tarefas supervisionadas e encerramento limpo.

O problema que este módulo resolve: uma biblioteca async que cria tarefas
soltas deixa o processo morrer com `Task was destroyed but it is pending`,
e exceções dentro de task silenciosamente somem até o GC.

Aqui, toda task criada pela KrynCord passa por um `Lifecycle`. Se o
encerramento vier, as tasks são canceladas e aguardadas — nunca abandonadas.

Usa `asyncio.TaskGroup` (3.11+) por baixo, que já entrega cancelamento
em cascata e propagação de exceção.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from types import TracebackType
from typing import Any, Self

from kryncord.errors import LifecycleError
from kryncord.logging import get_logger

__all__ = ["Lifecycle", "LifecycleError"]

log = get_logger("lifecycle")


class Lifecycle:
    """Supervisiona as tarefas de uma camada e garante encerramento limpo.

    Uma instância por camada (`http`, `gateway`) — assim o encerramento do
    REST não cancela a task do Gateway antes da hora.

    Uso::

        async with Lifecycle("gateway") as lc:
            lc.spawn(self._heartbeat_loop())
            lc.spawn(self._receive_loop())
            ...
    """

    __slots__ = ("_entered", "_group", "_name", "_tasks")

    def __init__(self, name: str) -> None:
        self._name = name
        self._group: asyncio.TaskGroup | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._entered = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def active_tasks(self) -> int:
        """Quantas tasks ainda estão vivas. Zero depois do `__aexit__`."""
        return sum(1 for task in self._tasks if not task.done())

    def spawn(
        self, coro: Coroutine[Any, Any, Any], *, name: str | None = None
    ) -> asyncio.Task[Any]:
        """Cria uma task supervisionada.

        Se o `Lifecycle` já fechou, cancela a coroutine imediatamente e
        levanta `LifecycleError` — nunca deixa a task órfã.
        """
        if self._group is None:
            coro.close()
            raise LifecycleError(
                f"{self._name}: spawn chamado fora do bloco `async with`. "
                "Toda task precisa nascer dentro do contexto."
            )

        task = self._group.create_task(coro, name=name or getattr(coro, "__name__", None))
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        log.debug("%s: task criada %s", self._name, task.get_name())
        return task

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        # A TaskGroup já retém a exceção e re-lança no __aexit__. Aqui só
        # garantimos que ela não passa despercebida no log.
        error = task.exception()
        if error is not None:
            log.error("%s: task %s falhou: %r", self._name, task.get_name(), error)

    async def __aenter__(self) -> Self:
        if self._entered:
            raise LifecycleError(f"{self._name}: Lifecycle não pode ser reutilizado")
        self._entered = True
        self._group = asyncio.TaskGroup()
        await self._group.__aenter__()
        log.debug("%s: ciclo aberto", self._name)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        group, self._group = self._group, None
        if group is None:
            return

        log.debug("%s: ciclo fechando (%d tasks ativas)", self._name, self.active_tasks)

        # Cancela antes de sair: "fechar" significa sair, não esperar. O
        # TaskGroup sozinho apenas *aguardaria* as tasks — deixaria um
        # sleep(60) pendurar o shutdown por 60 segundos.
        for task in tuple(self._tasks):
            if not task.done():
                task.cancel()

        try:
            # (None, None, None) é intencional. Se passássemos a exceção do
            # corpo, o TaskGroup a embrulharia num ExceptionGroup — e o erro
            # do usuário tem que sair intacto, não re-embalado.
            await group.__aexit__(None, None, None)
        except BaseExceptionGroup as task_errors:
            # Aqui só há erro de task: o corpo não falhou.
            if exc is None:
                raise
            # O corpo falhou. O erro do corpo tem precedência e vai
            # propagar por si só (retornar None não suprime); o das tasks
            # não some — fica no log.
            log.error(
                "%s: %d task(s) falharam no encerramento, subordinadas ao erro do corpo: %r",
                self._name,
                len(task_errors.exceptions),
                task_errors,
            )
        finally:
            self._tasks.clear()
