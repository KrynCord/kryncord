"""Importa `b`, que importa `a` de volta — o ciclo começa aqui.

O `B` é usado de verdade (`A = f"a/{B}"`), e não só importado por
conveniência: um import não usado seria `F401` e o `ruff --fix` o
removeria, deixando o fixture sem ciclo — e o teste passando por motivo
errado.
"""

from pacote_circular.b import B

A = f"a/{B}"
