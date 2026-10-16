"""Importa `a` de volta, que está no meio do import — é aqui que o
Python reclama.

O `A` é usado de verdade, e não só importado por conveniência: um
import não usado seria `F401` e o `ruff --fix` o removeria, deixando o
fixture sem ciclo — e o teste passando por motivo errado.
"""

from pacote_circular.a import A

B = f"b/{A}"
