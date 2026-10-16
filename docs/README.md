# Documentação

O que cada pasta é, e quando você abre cada uma.

| Pasta | Abra quando… |
|---|---|
| [`api/`](api/) | Quiser saber como a superfície pública se comporta — as regras de negócio, não o código. |
| [`decisions/`](decisions/) | Quiser saber **por que** o código é assim. ADRs numerados, um por escolha. |
| [`guides/`](guides/) | Quiser executar um procedimento passo a passo. |
| [`internals/`](internals/) | Quiser ver o desenho das camadas e o plano original. |
| [`reference/`](reference/) | Quiser o material externo que serviu de inspiração. |

## Ordem de leitura para quem chega agora

1. [`internals/initial-decisions.md`](internals/initial-decisions.md) — as
   dez decisões que definem o projeto, em onze linhas.
2. [`internals/architecture.md`](internals/architecture.md) — o desenho
   completo: camadas, módulos e limites.
3. [`decisions/`](decisions/) — na ordem dos números. Cada ADR explica o
   que foi considerado, o que foi escolhido e o que foi descartado. Um
   ADR **não é atualizado** quando a decisão muda: nasce um novo com
   número maior, e o antigo fica como registro.

## Duas distinções que a documentação inteira repete

**Ausente ≠ default.** Campo que o Discord não mandou chega `None`, e
nunca é preenchido com um valor de convenção. `""` e `None` não são a
mesma coisa, e um canal sem `rate_limit_per_user` não é um canal com
`rate_limit_per_user = 0`.

**REST ≠ Gateway.** São camadas independentes: dá para usar `client.api`
sem abrir o socket, e o Gateway fica vivo mesmo se o REST falhar.

## Publicar

O passo a passo de publicação — incluindo TestPyPI, Trusted Publishing e
por que `pip install --pre` é obrigatório para beta — está em
[`guides/publication.md`](guides/publication.md).
