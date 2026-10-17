"""Handler definido aqui e registrado por outro módulo.

É o caso do `__init__.py` que só re-exporta (`0027` §7): o comando
"pertence" a este módulo mesmo tendo sido registrado de fora, e o
`load_logs` só acerta se agrupar pelo `handler.__module__` depois de
tudo ter sido importado — não pelo delta de cada import.

Nada é registrado na importação: este módulo só **define**.
"""

from __future__ import annotations

from kryncord.interactions import CommandInteraction


async def orfao(inter: CommandInteraction) -> None:
    """Nunca roda — só existe para ser registrado por quem importa."""
    raise AssertionError("o handler do fixture não deve ser chamado")
