"""A cadeia de middleware: `compose` para juntar, `block` para abortar.

A assinatura é uma só nas três categorias — `fn(ctx, block)`, com `block`
sempre no segundo lugar (`0017`). Este módulo é o que existe **em
comum** entre comando, responder e evento: um para somar middlewares
numa `Options` que aceita uma função por tipo, e outro para abortar a
cadeia inteira de onde quer que seja chamado.

Ficam em `internal/` porque são a camada que os três despachos
compartilham. Um deles morando dentro de `responders/` faria `events/`
importar `responders/` para usar uma função de duas linhas — e acoplamento
circular por conveniência é o tipo de coisa que só se cobra depois.

## Por que `block` é exceção, não flag

Levanta de qualquer profundidade da pilha: dentro de ``if``, depois de
``await``, no meio de ``try``, sem precisar de ``return`` em cada caminho
de saída. Quem esquece o ``return`` com flag deixa o resto dos handlers
rodando em silêncio, que é o pior resultado possível — é a cadeia
continuando para trás de quem mandou parar.

## Por que middleware síncrona é erro no registro

A mesma razão dos handlers (`0006`, `0010`): middleware que não
`await`a nada de I/O ainda é assíncrona por natureza — verificar
permissão remota, cachear, esperar outra coisa. Aceitar síncrona aqui
criaria dois contratos para a mesma palavra, e o dia em que alguém
trocar uma pela outra com `await` a mais ou a menos, o bug não aparece
onde o erro apareceria.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from kryncord.errors import BlockHandlers

#: Qualquer middleware das três categorias. O `ctx` é o da categoria
#: (comando, responder ou evento) e o `block` é sempre o segundo.
Middleware = Callable[[Any, Any], Awaitable[None]]


def block(*tags: str) -> None:
    """Aborta middleware, handler **e** `on_not_found` (0017).

    Os `tags` são anotações livres de quem bloqueou — aparecem no log do
    despacho. São opcionais porque o uso comum é `block()` sem nada.
    """
    raise BlockHandlers(tags)


def compose(*cadeias: Middleware) -> Middleware:
    """Junta middlewares numa só, respeitando a ordem de registro.

    O resultado roda a primeira até a última, e qualquer `block()` a
    meio caminho aborta as que faltam — é o mesmo comportamento da cadeia
    que os despachos rodam, porque seria contraditório que a composição
    mudasse o que a cadeia faz.

    **Valida na chamada, não no dispatch.** Middleware síncrona levanta
    `TypeError` com o nome da função e o índice — descobrir isso no
    clique seria descobrir depois do botão publicado.
    """
    for indice, item in enumerate(cadeias):
        if not inspect.iscoroutinefunction(item):
            nome = getattr(item, "__qualname__", repr(item))
            raise TypeError(
                f"middleware {indice} ({nome}) deve ser assíncrona: "
                "escreva `async def` — middleware nunca devolve valor, "
                "então não há caso em que `def` basta"
            )

    if not cadeias:
        return _vazia
    if len(cadeias) == 1:
        return cadeias[0]

    async def composta(ctx: Any, block_fn: Any) -> None:
        """Roda cada middleware em ordem, na mesma cadeia do despacho."""
        for item in cadeias:
            await item(ctx, block_fn)

    composta.__qualname__ = " + ".join(
        getattr(item, "__qualname__", "middleware") for item in cadeias
    )
    return composta


async def _vazia(ctx: Any, block_fn: Any) -> None:
    """Uma cadeia vazia roda nada e não derruba o dispatch.

    Existe como função nomeada em vez de lambda para aparecer legível
    numa pilha — o `mypy` e o `traceback` agradecem.
    """
    return None
