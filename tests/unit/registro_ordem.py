"""Ordem de import observável — fica fora dos pacotes-fixture.

O registro vive aqui, e não em `pacote_teste/__init__.py`, por um motivo
bem concreto: o fixture precisa ser importado **pelo bootstrap**, e um
teste que precisasse ler a lista importaria o pacote antes e esconderia
o próprio `pacote_teste` de dentro do resultado.

Este módulo não é pacote-fixture, então ninguém o limpa de
`sys.modules` — e a lista é a mesma para quem importa de qualquer lado.

Fora de teste não é importado: os pacotes-fixture só existem dentro de
`tests/unit/`.
"""

ORDEM: list[str] = []
