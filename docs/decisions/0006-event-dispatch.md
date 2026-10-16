# 0006 — Eventos: payload tipado e política de dispatch

**Data:** 2026-10-11
**Status:** aceita

## Contexto

O Gateway entregava `("MESSAGE_CREATE", {...})` e o handler recebia o dict
cru. O smoke test da Fase 2 era inteiro `data.get("content")` e
`autor.get("username")` — funcionava, mas sem autocomplete, sem tipo, e
sem dizer quando o payload mudasse. Era o oposto do que uma biblioteca
promete.

Havia também uma decisão de execução pendente, explicitamente pedida pelo
`KrynCord-ARCHITECTURE.md` §6: "O dispatcher deve definir se handlers são
executados em sequência ou em tarefas independentes. A política deve ser
documentada e testada, inclusive para exceções e cancelamento."

## Decisão

### Payloads chegam interpretados

`EventDispatcher` mantém um registro `evento → parser`, e converte o
payload antes de entregar. `MESSAGE_CREATE` vira `Message`, `READY` vira
`Ready`, `MESSAGE_DELETE` vira `PartialMessage`. Eventos sem parser chegam
cru — a biblioteca não finge que entende o que ainda não interpretou.

Nomes aceitam as duas formas. `client.on("MESSAGE_CREATE")` e
`client.on("message_create")` caem na mesma gaveta, normalizadas por
`events/names.py`. As duas continuam registradas porque trocar o nome de
uma hora para outra quebraria compatibilidade sem ganhar nada.

### `from_payload` devolve `None` quando falta o campo essencial

Um `Message` sem `id` não é mensagem. Antes, `from_payload` devolvia o
objeto com `id=0` — e o handler perseguiria um ID que não existe, com um
404 como recompensa.

Agora devolve `None`, e o **dispatcher entrega o payload cru** nesse caso.
Objeto inútil seria pior que dict, porque o dict pelo menos deixa o
usuário ver o que chegou.

Isto vale para o `id` de `Message`, `Channel`, `Guild`, `User`,
`Attachment` e os três `Partial*`. `Ready` é a exceção documentada: é
anúncio de sessão, não entidade, e continua útil sem `session_id`.

### Handlers têm que ser `async`

Validado no registro, uma vez, com `TypeError`. Sem a validação, o `await`
falharia a cada evento, o dispatcher logaria e ignoraria, e o sintoma —
handler que nunca roda, sem erro visível — é dos piores de diagnosticar.

A validação usa um helper que cobre `async def`, `functools.partial` de
`async def` e objetos com `async def __call__`. `inspect.iscoroutinefunction`
sozinho rejeitaria o último caso legítimo.

### Execução sequencial, na ordem de registro

A alternativa — uma task por handler — daria ordem imprevisível entre
handlers do mesmo evento, e imprevisibilidade num dispatch de mensagem é
como se fabrica bug de corrida. Quer paralelismo? `Client.spawn` dentro do
handler, e aí quem escolhe a ordem é o autor.

### Exceção é isolada, cancelamento propaga

Handler que levanta é logado e o próximo roda. Derrubar a conexão por um
`KeyError` num log seria trocar um evento perdido por um bot fora do ar —
e o bot fora do ar perde *todos* os eventos.

Cancelamento é diferente, e não é erro: é o `close()` mandando o bot
desligar. Engolir `CancelledError` deixaria tarefa pendurada no shutdown.
Por isso o `except` específico vem antes do `except Exception`.

## Consequências

- `Client.on()` não muda de forma, só muda o que o handler recebe. Quem
  já escutava `dict` agora recebe modelo.
- Custo por dispatch: um `dict.get` no registro e um parse por evento.
  Negligível perto do custo de round-trip do Gateway.
- `models/partial.py` passa a ser a resposta para eventos que o Discord
  entrega incompletos de propósito, em vez de `Message` com defaults.
- Sem `Message.clean_content`: trocar `<@123>` por `@123` não ajuda, e
  trocar por nome exige resolver o ID — trabalho do cache, ainda não
  existente. Propriedade que parece ajudar e não ajuda é pior que
  ausente.

## Escopo desta fase

Só os modelos de que o caminho mínimo precisa, e os eventos que os
consomem:

| Modelo | Eventos |
|---|---|
| `Ready` | `READY` |
| `Message` | `MESSAGE_CREATE`, `MESSAGE_UPDATE` |
| `PartialMessage` | `MESSAGE_DELETE` |
| `Guild` | `GUILD_CREATE`, `GUILD_UPDATE` |
| `PartialGuild` | `GUILD_DELETE` |
| `Channel` | `CHANNEL_CREATE`, `CHANNEL_UPDATE` |
| `PartialChannel` | `CHANNEL_DELETE` |

Ficaram de fora, por ainda não terem consumer: `Role`, `Emoji`,
`Reaction`, `Webhook`, `Interaction`. Entra quando um endpoint ou um
evento concretamente precisar — a regra da `0003` vale.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Handlers síncronos aceitos | Convidaria a bloquear o event loop dentro do dispatch, e o sintoma (bot parado, sem erro) é o pior de diagnosticar. |
| Um task por handler | Ordem imprevisível entre handlers do mesmo evento. |
| `from_payload` sempre devolve objeto | Objeto com `id=0` faz o handler perseguir algo que não existe. |
| `EventName` como única forma de registro | Quebraria `client.on("READY")` já em uso, sem ganho. |
| `Message.clean_content` sem cache | Troca uma mention por um ID — não resolve o que promete. |

## Referências

- `KrynCord-ARCHITECTURE.md` §6 (`models/`, `events/`)
- `ideias/10-events.md` — `@event`, nomes em snake_case
- `docs/decisions/0003-data-models.md` — por que dataclasses e o
  contrato de ausência
