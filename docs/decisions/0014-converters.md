# 0014 — Registrador de conversores

## Contexto

A ideia 08 §6 descreve o dispatcher de roteador e o registro de
conversores, mas não fecha:

- a assinatura do conversor (recebe `client`? `cache`? só o `raw`?)
- se conversores são síncronos ou assíncronos
- como o conversor do Discord (`User`, `Member`, `Role`, `Channel`)
  resolve a entidade
- a ordem de `parse=` sobre o valor convertido

E o `0008` mostrou ao vivo que `Member` e `Role` não carregam `guild_id` —
quem sabe em que guild eles estão é quem leu o evento.

## Decisão

### Assinatura única: `fn(raw: str, ctx) -> T`

O `ctx` é o `ResponderContext` que já existe. Ele tem `.client`,
`.cache` (o `ConnectionState`), `.interaction` e `.params`. Não há um
terceiro objeto de contexto de conversão.

Conversores que não precisam de nada ignoram o segundo argumento.

### Conversores aceitam síncrono e assíncrono

`inspect.iscoroutinefunction` decide — o mesmo critério de
`before_load` na 01 §B3.

- Padrão síncrono (int, str, bool): não paga `await`
- Assíncrono quando a resolução pode ir à REST (`User` ausente do cache)

**Não** embrulhar síncrono em coroutine: uma `await` por parâmetro por
invocação é o custo que a disciplina síncrona existe para evitar.

### Conversores do Discord: cache → REST → `ConversionError`

| Passo | O quê |
|---|---|
| 1 | `client.cache.get_user(id)` / `get_member` / `get_role` / `get_channel` |
| 2 | Se `None`, vai à REST (`api/` já tem os métodos) |
| 3 | Se falhar, `ConversionError` com o valor e o nome do parâmetro |

Cache primeiro porque é O(1) e já quente depois do READY; REST porque
conversão falhando num usuário que existe seria um bug não-falso-positivo.

`Member`/`Role` sem `guild_id` no modelo: quem resolve sabe a guild — é
`ctx.interaction.guild_id`. O conversor preenche a partir do contexto,
não do modelo.

### Conjunto mínimo obrigatório

`str`, `int`, `float`, `bool`, `datetime`, `UUID`, `Literal[...]`,
`StrEnum`, `T | None`, e os do Discord: `User`, `Member`, `Channel`,
`Role`, `Message`.

### `datetime` aceita ISO e epoch, por formato

```
valor.isdigit() e len == 10  -> epoch em segundos
valor.isdigit() and len == 13 -> epoch em milissegundos
senão                         -> datetime.fromisoformat
```

A regra é uma só linha e cobre os dois formatos reais. ISO sempre tem
`-` ou `:`, então `isdigit()` não colide.

### `parse=` faz merge por cima, pela regra do `0008`

Já fechado em `0008`: top-level presence no payload bruto. Aqui é só
reafirmado — `parse=` recebe `(raw, ctx)` e o resultado vence o valor
convertido.

### Resolver hints é uma vez por função

`get_type_hints` com `lru_cache` em `id(fn)`. As funções vivem para
sempre no registry (registram no import), então não há fuga de id.

Sem isso, cada invocação de roteador recomputaria a resolução de tipos
— o gargalo mais fácil de gastar sem perceber.

### Erro → `ConversionError` → `on_error` do responder

Não vira resposta automática. O `on_error` decide; o default do `0017`
loga e responde efêmera.

## Consequências

- `responders/converters.py` importa `state/` e `api/` — a única
  dependência "lateral" da Fase 4, e ela é justificada: conversar é
  resolver entidade.
- Conversores custom podem ir à REST sem reinventar a injeção.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `fn(raw) -> T`, sem contexto | Conversor do Discord não tem como resolver `User` |
| `ConverterContext` novo com `.client`/`.cache` | Um objeto a mais para aprender, quando o `ResponderContext` já tem os dois |
| Todo conversor `async` | `await` por parâmetro por invocação, para `int` |
| Só cache, sem REST | `User` fora do cache viraria erro falso-positivo |
| Resolver `guild_id` do modelo | `Member` e `Role` não têm — verificado ao vivo no `0008` |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 22 Contexto | `Member`/`Role` sem `guild_id` é um fato verificado ao vivo; qualquer conversor que leia do modelo estaria errado |
| 02 Performance | Cache primeiro, REST só no miss, `lru_cache` nos hints — três decisões que são o mesmo princípio |
| 07 Concorrência | REST assíncrono no conversor é I/O dentro de uma coroutine — natural, mas é o único ponto onde um parâmetro custa rede |
| 11 Idiomático | `isdigit()` + `len` é mais legível que uma gramática de data |
| 09 Testes | Cache → REST → erro dá três caminhos determinísticos para testar |
| 17 Crítico | Perguntou se a REST no conversor não violava "roteamento é barato"; resposta: só no miss, e o alternative é falhar com dado válido |

**Veredito do juiz: APROVADO COM AJUSTES.** O ajuste: registrar
explicitamente que a REST é só no miss, para não virar prática de
conversor sair buscando tudo.

**Divergência preservada:** o Participante 03 (CPU) notou que o
`lru_cache` em `id(fn)` é tecnicamente seguro só porque o registry não
remove funções — se um `unregister` existir amanhã, o cache precisa de
limpeza. Fica registrado como restrição futura.

**Confiança: 89%.**
