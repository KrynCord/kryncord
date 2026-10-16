# 0020 — Eventos: `@event`, `EVENT_PAYLOADS` e `dispatch_mode`

## Contexto

A ideia 10 descreve `@event`, `EVENT_PAYLOADS`, `EventContext`,
`dispatch_mode`, tags e `on_error`. A 06 §11 mostra `@event("ready")`.

O `0006` já construiu `events/dispatcher.py` com `REGISTRY` (10 eventos,
parser por evento) e `client.on(name)`. A pergunta é o que a 10 acrescenta
— e se `EVENT_PAYLOADS` substitui o `REGISTRY`.

E há um problema que ninguém viu: `message_update → (old, new)` exige
ler o `old` **antes** do updater aplicar a mudança, enquanto o `0008`
decidiu que o cache é atualizado antes dos handlers.

## Decisão

### `EVENT_PAYLOADS` e `REGISTRY` são camadas diferentes, não tabelas concorrentes

| Camada | Quem | O quê |
|---|---|---|
| `REGISTRY` (0006) | parser do payload cru | evento → **um** objeto interpretado |
| `EVENT_PAYLOADS` (nova) | assinatura do handler | evento → **tupla de argumentos** |

`EVENT_PAYLOADS` **referencia** os parsers do `REGISTRY`. Para
`message_create`, `REGISTRY["message_create"]` devolve `Message`, e
`EVENT_PAYLOADS["message_create"]` é `(Message,)` — um argumento só.

Para `message_update`, o parser devolve `Message`, e
`EVENT_PAYLOADS["message_update"]` é `(Message | None, Message)` — dois
argumentos, porque a semântica do evento é "o que era e o que é".

Nenhuma tabela duplica a outra; uma descreve parsing, a outra assinatura.

### O `old` é capturado numa instantânea antes do updater

`Client._dispatch` ganha um passo:

```
1. snapshot   -> para cada evento que declara um item `old`, ler do cache
2. updater    -> EventUpdater.apply (0008)
3. ready      -> _ready.set() em READY/RESUMED
4. handlers   -> despacho
```

Sem o snapshot, `message_update` entregaria `old == new`. O `0008`
"cache antes dos handlers" continua verdadeiro — o que muda é que
o updater lê o valor antigo **antes** de sobrescrever.

Só eventos com `old` pagam o snapshot. `message_create`, `ready` e
`interaction_create` pagam um `if` vazio.

### `@event` e `client.on()` coexistem, no mesmo registry, com um flag

| Forma | Entrega | Caminho |
|---|---|---|
| `client.on("message_create")` | argumentos crus | registro de baixo nível (0006) |
| `@event("message_create")` | `EventContext` primeiro | registro de alto nível |

O `EventDispatcher` guarda `(handler, with_context)` e chama de acordo.
Um booleano por handler, sem ambiguidade, e o `client.on` continua
exatamente como está — nenhum contrato do `0006` quebra.

### `EVENT_PAYLOADS` completo, agora

Os 10 do `0006` mais os que a 10 §2 lista:

```
ready                   -> ()
resumed                 -> ()
message_create          -> (Message,)
message_update          -> (old, new)
message_delete          -> (id, old)
message_delete_bulk     -> (ids, olds)
interaction_create      -> (Interaction,)
guild_create            -> (Guild,)
guild_update            -> (old, new)
guild_delete            -> (id, old)
channel_create          -> (Channel,)
channel_update          -> (old, new)
channel_delete          -> (id, old)
typing_start            -> (TypingStart,)
voice_state_update      -> (old, new)
```

Só 15 por enquanto. A tabela cresce com o que a biblioteca já sabe
parsear — sem inventar evento que não tem parser.

### `ready` é `once=True`, por força

Registrado múltiplas vezes → uma entrada só, com aviso. O `ready` não
pode disparar duas vezes, e o dispatcher é o único lugar que sabe.

### `dispatch_mode="concurrent"` usa TaskGroup por dispatch

`sequential` continua o default (K6, decidido no `0009`).

`concurrent` cria um `TaskGroup` por dispatch e espera todos. O
cancelamento no shutdown alcança as tasks porque o TaskGroup é filho do
dispatch, que é filho do Client.

Handlers recebem **cópia** da lista de handlers em `concurrent` — em
`sequential`, recebem a lista viva (porque a mutação é o recurso
documentado da `10` §8).

### `client.dispatch(name, *args)` existe

Hook de teste. É como o `FakeGatewayTransport` entrega sem tocar na rede.

### `EventDefinitionError` sugere o mais próximo

`difflib.get_close_matches` sobre o `EVENT_PAYLOADS` — a mesma
comportamento dos `create_*` do `0009`. Mensagem: "evento 'message_craete'
não existe; quis dizer 'message_create'?".

### Handlers continuam assíncronos, inclusive via `@event`

`TypeError` no registro, mesmo critério do `0006`. K9 (`*args` aceito)
não muda isso — aceitar `*args` é aceitar a quantidade de argumentos,
não a sincronicidade.

## Consequências

- `client.py:_dispatch` cresce de um passo para quatro — a instantânea é
  condicional, e o custo é um `if` para os eventos sem `old`
- `events/dispatcher.py` ganha `with_context` por handler e o
  `once=True` do `ready`
- `events/names.py` passa a ser a fonte única de nomes, e `EVENT_PAYLOADS`
  dela deriva

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `EVENT_PAYLOADS` substitui `REGISTRY` | São perguntas diferentes: como parsear vs quantos argumentos |
| `old` lido pelos handlers | Cada handler leria o cache depois do updater — `old == new` em todos |
| `@event` vira o único caminho | Quebra `client.on` do `0006` e obriga a Context para o caso simples |
| Snapshot de todo o cache | Custaria um dict inteiro por dispatch para os eventos que não precisam |
| Handlers síncronos permitidos no `@event` | Contradiz o `0006`; dois critérios de "handler válido" |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 19 Analista | `message_update → (old, new)` com o cache já atualizado é um erro silencioso — o mais perigoso dos cinco |
| 06 Arquitetura | `REGISTRY` e `EVENT_PAYLOADS` respondem perguntas diferentes; fundir seria perda de informação |
| 07 Concorrência | TaskGroup por dispatch dá cancelamento sem código novo |
| 09 Testes | `client.dispatch(name, *args)` é o hook que permite testar qualquer evento sem gateway |
| 08 Segurança | `ready` `once=True` é a proteção contra "dois clientes respondendo o mesmo evento" |
| 11 Idiomático | `difflib` no erro de nome é o mesmo padrão dos `create_*` — consistência de erro |
| 18 Pragmático | 15 eventos é o que já tem parser; crescer a tabela sem parser é mentira |

**Veredito do juiz: APROVADO COM AJUSTES.** O Juiz pediu que a
instantânea seja explícita no código e testada com um evento `old`.
Incorporado.

**Divergência preservada:** o Participante 05 (GPU) e o 13 (baixo
consumo) observaram que a instantânea aloca uma tupla por evento com
`old`. Não mudou a decisão — é uma tupla curta por dispatch, e sem ela
o resultado é errado.

**Confiança: 87%.**
