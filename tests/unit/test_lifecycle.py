"""Testes de `kryncord.lifecycle` — encerramento limpo e spawn."""

from __future__ import annotations

import asyncio

import pytest

from kryncord import Lifecycle, LifecycleError


async def test_spawn_inside_context_works() -> None:
    ran = asyncio.Event()

    async def work() -> None:
        ran.set()

    async with Lifecycle("test") as lc:
        lc.spawn(work())
        await asyncio.wait_for(ran.wait(), timeout=1)

    assert lc.active_tasks == 0


async def test_spawn_outside_context_raises() -> None:
    async def work() -> None:
        return None

    lc = Lifecycle("test")
    with pytest.raises(LifecycleError, match="fora do bloco"):
        lc.spawn(work())


async def test_spawn_outside_context_does_not_leak_task() -> None:
    """A coroutine tem que ser fechada, senão o GC reclama depois."""

    async def work() -> None:
        return None

    lc = Lifecycle("test")
    with pytest.raises(LifecycleError):
        lc.spawn(work())

    # Nenhuma task viva ligada ao loop.
    await asyncio.sleep(0)
    assert lc.active_tasks == 0


async def test_close_cancels_running_task() -> None:
    cancelled = asyncio.Event()

    async def forever() -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async with Lifecycle("test") as lc:
        lc.spawn(forever(), name="forever")
        assert lc.active_tasks == 1
        # A task precisa de um tick para começar — cancelar antes de rodar
        # não executa o corpo dela (ver test_multiple_tasks_all_cancelled).
        await asyncio.sleep(0)

    await asyncio.wait_for(cancelled.wait(), timeout=1)


async def test_active_tasks_zero_after_close() -> None:
    async def forever() -> None:
        await asyncio.sleep(60)

    async with Lifecycle("test") as lc:
        lc.spawn(forever())
        assert lc.active_tasks == 1

    assert lc.active_tasks == 0


async def test_cannot_reuse_lifecycle() -> None:
    lc = Lifecycle("test")
    async with lc:
        pass

    with pytest.raises(LifecycleError, match="não pode ser reutilizado"):
        async with lc:
            pass


async def test_exception_in_task_propagates_on_close() -> None:
    """Exceção de task não some silenciosamente.

    Vem como ExceptionGroup, mesmo com uma só — é o contrato do
    asyncio.TaskGroup e não devemos "desembrulhar" de forma inconsistente
    (uma task viraria RuntimeError, duas virariam ExceptionGroup).
    """

    async def boom() -> None:
        raise RuntimeError("explodiu")

    with pytest.raises(BaseExceptionGroup) as info:
        async with Lifecycle("test") as lc:
            lc.spawn(boom())
            await asyncio.sleep(0)

    assert len(info.value.exceptions) == 1
    assert isinstance(info.value.exceptions[0], RuntimeError)
    assert str(info.value.exceptions[0]) == "explodiu"


async def test_body_exception_is_not_wrapped_in_group() -> None:
    """O erro do corpo sai intacto.

    Sem isto, `async with Client(cfg): raise ValueError` devolveria um
    ExceptionGroup e quebraria o código do usuário.
    """

    async def work() -> None:
        await asyncio.sleep(60)

    with pytest.raises(ValueError, match="boom"):
        async with Lifecycle("test") as lc:
            lc.spawn(work())
            await asyncio.sleep(0)
            raise ValueError("boom")


async def test_name_is_exposed() -> None:
    assert Lifecycle("gateway").name == "gateway"


async def test_spawn_accepts_name_override() -> None:
    started = asyncio.Event()

    async def work() -> None:
        started.set()

    async with Lifecycle("test") as lc:
        task = lc.spawn(work(), name="minha-task")
        assert task.get_name() == "minha-task"
        await asyncio.wait_for(started.wait(), timeout=1)


async def test_multiple_tasks_all_cancelled() -> None:
    cancelled_count = 0

    async def forever(index: int) -> None:
        nonlocal cancelled_count
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled_count += 1
            raise

    async with Lifecycle("test") as lc:
        for i in range(5):
            lc.spawn(forever(i))
        assert lc.active_tasks == 5
        # Dar um tick para as tasks começarem: cancelar uma task que ainda
        # não rodou descarta a coroutine sem executar o corpo, e o handler
        # de CancelledError nunca dispararia.
        await asyncio.sleep(0)

    assert cancelled_count == 5
