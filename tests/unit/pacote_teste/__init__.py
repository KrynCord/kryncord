"""Pacote-fixture da descoberta — importar tem que ser observável.

Cada módulo anota o próprio nome em `registro_ordem.ORDEM`, na ordem em
que foi executado. É o que permite testar a garantia do `0019` (pai
antes de filho) sem inspecionar `sys.modules`, que já estaria populado
por qualquer teste anterior.

Os testes limpam `ORDEM` e tiram `pacote_teste*` de `sys.modules` antes
de cada caso — senão o cache do import faria o segundo teste ver a lista
vazia e concluiria que nada foi carregado.
"""

from registro_ordem import ORDEM

ORDEM.append("pacote_teste")
