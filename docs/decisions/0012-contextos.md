# 0012 — Contextos: `CommandContext`, `ResponderContext`, `EventContext`

## Contexto

Cinco ideias descrevem contextos por conta própria (03, 05, 06, 07, 10, 14)
e cada uma inventou um pouco da superfície:

- `is_replied()` (03 §5) contra `is_responded()` (06, 07, 14)
- `show_modal` (06 §11) contra `send_modal` (07 §6, 14 §11)
- `ctx.state` visto como estado do comando (03) e estado por dispatch (10 §2)
- `ctx.spawn` descrito só para eventos (10 §2)
- `ctx.options.focused()` (06 §7) duplicando o que o `AutocompleteContext` já traz

Mais a divisão entre `interactions/context.py` e `commands/context.py`,
que precisa de uma régua — dois "contextos" com a mesma palavra.

## Decisão

### Um só nome por pergunta

| Pergunta | Nome | Abandonado |
|---|---|---|
| Já respondi? | `is_responded()` | `is_replied()` |
| Abrir modal | `send_modal` | `show_modal` |
| Foco do autocomplete | `AutocompleteContext.focused` | `ctx.options.focused()` |

Três nomes, três respostas. O `is_replied()` do 03 era o mais antigo das
ideias — as cinco posteriores já escreviam `is_responded()`, e o plural é
mais fiel: um defer já respondeu.

### `ctx.state` é `dict[str, Any]` criado por dispatch

Nasce vazio no `_dispatch`, vive entre o `_update_cache` e o último handler,
morre no fim. Compartilhado por middleware e handlers do **mesmo** dispatch,
nunca entre dois.

`ctx.state["key"]` é a forma documentada de uma middleware passar dado a um
handler sem colidir com os 20 atributos do próprio contexto.

### `spawn` fica em `internal/tasks.py`, exposto nos três contextos

`internal/timing.py` já existe para relógio; `internal/tasks.py` junta o
`spawn()` da ideia 10 com o `create_task` que o `Client._dispatch` já faz.

`CommandContext`, `ResponderContext` e `EventContext` têm `spawn` — a
necessidade de disparar trabalho em background é a mesma nos três, e
omitir dos comandos seria uma omissão por acidente.

### Divisão de responsabilidade entre os dois arquivos de contexto

| Arquivo | Dono | Faz |
|---|---|---|
| `interactions/context.py` | `InteractionContext` | máquina de estados + `reply`/`defer`/`edit`/`delete`/`follow_up`/`send_modal`/`ack`/`is_responded` |
| `commands/context.py` | `CommandContext` | campos do comando, opções, alvo de context menu |
| `responders/context.py` | `ResponderContext` | `params`, `custom_id`, `client` |
| `events/context.py` | `EventContext` | nome do evento, args, `block` |

A régua é: **`InteractionContext` é o dono de responder.** Os outros
compostam, não herdam. `CommandContext.reply(...)` é delegação, não
reimplementação — e um só `InteractionContext` por dispatch significa que
`ctx.reply()` e `ctx.interaction_ack()` (se existissem) nunca discordam.

### `ctx.interaction` devolve o modelo `Interaction`

O modelo continua dado puro (`0003`). Quem quer ler `interaction.data`
lê; quem quer responder chama `ctx.reply`.

### `ctx.options` é um accessor tipado

```python
ctx.options.get_string("nome")
ctx.options.get_int("pontos")
ctx.options["nome"]  # devolve o valor já convertido
ctx.options.ficha  # atributo só para opção declarada
```

`AttributeError` para opção não declarada, `KeyError` para chave
desconhecida no `[]`. Duas exceções diferentes porque são dois erros
diferentes: "você digitou errado" e "essa opção não existe".

### `ctx.target_*` só existe em context menu

`target_user`, `target_member`, `target_message` — presentes em
`CommandContext` de `USER`/`MESSAGE`, `AttributeError` em `CHAT_INPUT`.
Acesso por atributo, sem checagem de tipo em cada campo.

### `ctx.args` continua sendo `list` mutável

Já decidido na `10` §8: a mutação propaga para os próximos handlers no
modo `sequential`. Fica documentado que é intencional e que é o cano para
reordenar argumentos.

## Consequências

- `CommandContext` cresce e precisa delegar 7 métodos — boilerplate, mas
  de um tipo só, gerável a mão uma vez.
- `EventContext` não tem `reply`: eventos não respondem. Tem `spawn` e
  `block`.
- `AutocompleteContext` herda a superfície comum mas **não** tem `reply` —
  só `respond(choices)`, porque o autocomplete é um tipo de resposta único.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Herança `EventContext -> CommandContext` | Campos de comando não fazem sentido em evento; composição com um nucleo comum é mais honesta |
| `InteractionContext` como atributo público `ctx.replies` | Segundo objeto para o usuário aprender; delegação esconde isso |
| `ctx.options.focused()` junto com `AutocompleteContext.focused` | Dois caminhos para a mesma informação, e um deles vive fora do autocomplete |
| Sem `spawn` nos comandos | Omissão acidental — a necessidade é idêntica |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 01 Simplicidade | Um nome por pergunta é a decisão mais barata do documento inteiro |
| 17 Crítico | Contra `is_replied`: cinco ideias posteriores já usavam `is_responded`, o 03 era o outlier |
| 06 Arquitetura | Dono único (`InteractionContext`) para o estado; compor em vez de herdar |
| 11 Idiomático | `AttributeError` para atributo e `KeyError` para chave são as exceções que o Python já dá de graça |
| 22 Contexto | Autocomplete **só** responde com escolhas — misturar `reply` ali faria o usuário mandar a resposta errada |
| 19 Analista | Registraram que `ctx.state` por dispatch é a única forma que não vaza entre mensagens |
| 07 Concorrência | `spawn` nos contextos é onde o cancelamento no shutdown tem que alcançar — task órfã no `Client` não teria o dono |

**Veredito do juiz: APROVADO COM AJUSTES.** O ajuste pedido pelo Juiz foi
tirar `reply` do `AutocompleteContext` (mudança já incorporada acima).

**Divergência preservada:** o Participante 05 (GPU/hardware) declarou que
sua área não se aplica e observou apenas que nenhum contexto precisa de
buffer — `ctx.state` é um dict simples, não uma estrutura grande.

**Confiança: 88%.**
