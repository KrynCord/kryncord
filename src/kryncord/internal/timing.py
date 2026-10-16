"""Relógio e espera — as duas abstrações que os testes trocam.

Nenhum teste do KrynCord dorme. Um heartbeat de 41 segundos ou um
rate limit de 5 minutos viram `FakeSleeper`, que só **anota** a espera
e **anda** o relógio. O efeito colateral é o que torna o teste útil:
quando o código calcula "esperar 5s" e o sleeper anda 5s, a próxima
iteração já enxerga a janela zerada — exatamente como aconteceria em
produção, só que instantâneo.

As anotações são o teste em si. `assert sleeper.calls == [0.0, 41.25]`
afirma alguma coisa sobre o protocolo; `await asyncio.sleep(41.25)` só
afirma que o teste demora.

Por que `monotonic` e não `time.time`:

* **Relógio de parede pula.** NTP, DST e correção manual de hora
  andam para trás. Um rate limit que mede com relógio de parede calcula
  um reset negativo e libera a requisição cedo — mandando direto para
  um 429.
* **Monotonic nunca volta.** Diferença de dois instantes é sempre o
  tempo decorrido de verdade, mesmo se alguém ajustar o relógio do
  servidor no meio da noite.

O relógio é um campo público injetável, não um monkeypatch: patch em
`time.monotonic` vaza para todo o processo e quebra teste paralelo.
Aqui, quem troca é quem constrói o objeto.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

#: Faz o quê: devolve os segundos decorridos desde um ponto arbitrário.
Clock = Callable[[], float]

#: Dorme — ou, em teste, finge que dormiu.
Sleeper = Callable[[float], Awaitable[None]]

#: Relógio monotônico de verdade. Nunca anda para trás.
monotonic_clock: Clock = time.monotonic


async def real_sleep(seconds: float) -> None:
    """Espera de verdade. Só sai do caminho em produção."""
    await asyncio.sleep(seconds)
