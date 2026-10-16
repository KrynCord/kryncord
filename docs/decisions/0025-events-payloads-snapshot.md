# 0025 — `EVENT_PAYLOADS` × `client.on`, a instantânea e os modelos de suporte

## Contexto

O `0020` fechou o contrato dos eventos: `EVENT_PAYLOADS` de 15 entradas,
instantânea do `old` antes do updater, `@event` com `EventContext`,
`ready` `once=True`, `concurrent` com `TaskGroup`, e
`client.dispatch` como hook de teste.

Codar o bloco levantou seis perguntas que o `0020` não respondeu — e uma
delas é factual: a tabela do próprio `0020` contradiz o `0006`.

### A contradição

O `0020` escreve `ready -> ()` e `resumed -> ()`. Mas:

- o `0006` decidiu "`READY` vira `Ready`", e a consequência escrita foi
  "`Client.on()` não muda de forma, só muda o que o handler recebe";
- `tests/unit/test_client.py` tem `@client.on("READY") async def pronto(data)`
  e `tests/unit/test_dispatcher.py` tem `test_ready_vira_modelo`;
- `bot testes/main.py` registra `pronto(ready: Ready)` e
  `retomado(data: object)`.

`ready -> ()` faria `client.on("READY")` receber **zero** argumentos — a
API de baixo nível não veria o anúncio de sessão. Isso não é um detalhe
de tabela, é o `0020` anulando o `0006` sem dizer.

### As outras cinco

1. A tabela do `0020` vale para `client.on` também, ou só para `@event`?
   A linha "argumentos crus" sugere que sim — mas aí `message_delete`
   passa de um argumento para dois.
2. `typing_start` e `voice_state_update` estão entre os 15, e nenhum dos
   dois tem modelo nem parser. A mesma decisão diz "sem inventar evento
   que não tem parser".
3. `voice_state_update -> (old, new)` exige ler o `old` no cache — e o
   cache **não guarda voice states**. Sem isso, `old` seria `None` para
   sempre dentro de uma assinatura que promete `VoiceState | None`.
4. `client.dispatch(name, *args)` — os `*args` são o payload cru (como o
   `FakeGatewayTransport` entrega) ou os argumentos já interpretados?
5. `concurrent`: o `0020` diz "cria um `TaskGroup` por dispatch e espera
   todos"; a ideia 10 §5 diz "o dispatcher não espera".

## Decisão

### 1. `EVENT_PAYLOADS` vale para as **duas** formas

| Forma | Chamada |
|---|---|
| `client.on("message_update")` | `await handler(*args)` |
| `@event("message_update")` | `await handler(ctx, *args)` |

Uma tabela, dois caminhos, e a única diferença é o `EventContext` na
frente. É o que a própria linha do `0020` diz ("argumentos crus" contra
"EventContext primeiro"), e é a única forma em que a validação de
aridade significa a mesma coisa nos dois registros.

A alternativa — `client.on` continuando com um payload único — deixaria a
API de baixo nível **pior** que a de alto nível: quem escreve
`client.on("message_delete")` não veria o `old`, e é justamente o `old`
que o payload cru não traz.

**Quebra registrada.** Seis eventos mudam de um argumento para dois:
`message_update`, `message_delete`, `message_delete_bulk`, `guild_update`,
`guild_delete`, `channel_update`, `channel_delete`. É pré-1.0, não está
em git, e adiar é quebrar depois com custo maior. A tabela completa está
em "Quebras" abaixo.

### 2. Correção da tabela: `ready -> (Ready,)` e `resumed -> (payload cru,)`

O `0020` escreveu `()`. Prevalece o `0006`, que é quem definiu o
contrato de `client.on` e cuja consequência escrita é "não muda de forma".

| Evento | Tabela corrigida | Por quê |
|---|---|---|
| `ready` | `(Ready,)` | `0006`; `Ready.from_payload` existe e nunca devolve `None` |
| `resumed` | `(Mapping[str, Any],)` | sem parser — `0006` entrega cru, e o payload é `{}` |

É a mesma classe de correção do `0024`, que registrou dois bugs de
implementação encontrados ao codar. Aqui o bug está no documento da
decisão, não no código — e a correção fica escrita aqui.

`resumed` é o único evento da tabela sem modelo. Manter `@event("resumed")`
funcionando com o dict cru é mais honesto que inventar `Resumed`, um
objeto com um campo.

### 3. A aridade é validada; a anotação, com folga

| Regra | Comportamento |
|---|---|
| Aridade errada | `EventDefinitionError` na importação: "esperado 2 argumentos, recebeu 1" |
| `*args` no handler | aceito, validação pulada (`K9`) |
| Evento desconhecido | `EventDefinitionError` com `difflib.get_close_matches` |
| Anotação incompatível | `EventDefinitionError` |
| Anotação ausente ou não resolvível | aceita (`ideia 10` §2, regra 3) |

A anotação entra só quando `get_type_hints` resolve **e** o tipo
declarado é incompatível com o da tabela. `Any`, `object`, ausência e
`NameError` de forward ref passam: a anotação é um ganho do editor, não
um contrato de runtime, e falhar num alias que o `mypy` aceita seria
pior que o alias.

### 4. A instantânea é um módulo próprio, e oito eventos pagam

`events/snapshot.py` com `instantanea(name, data, state)`. Chamado por
`Client._dispatch` **antes** do `_update_cache`, e só.

| Paga instantânea | Lê |
|---|---|
| `message_update`, `message_delete` | `state.get_message(id)` |
| `message_delete_bulk` | um `get_message` por id da lista |
| `guild_update`, `guild_delete` | `state.get_guild(id)` |
| `channel_update`, `channel_delete` | `state.get_channel(id)` |
| `voice_state_update` | `state.get_voice_state(guild, user)` |

Os outros sete pagam um `if` vazio — a alternativa (snapshot de todo o
cache) custaria um dict inteiro por dispatch.

A ordem do `0020` fica:

```
1. instantânea  -> lê do cache o que o updater vai sobrescrever
2. updater      -> EventUpdater.apply (0008)
3. ready        -> _ready.set() em READY/RESUMED
4. roteamento   -> INTERACTION_CREATE vai aos registries (0026)
5. handlers     -> despacho, com os args montados
```

### 5. Modelos de suporte entram: `TypingStart` e `VoiceState`

As duas únicas formas de honrar a lista dos 15 sem entregar `old=None`
numa assinatura que promete `VoiceState`.

| Modelo | Campos essenciais | Onde entra |
|---|---|---|
| `TypingStart` | `channel_id`, `guild_id`, `user_id`, `timestamp`, `member` | `models/typing.py` |
| `VoiceState` | `channel_id`, `user_id`, `session_id`, `deaf`/`mute` e os `self_*`, `member` | `models/voice.py` |

`from_payload` devolve `None` sem `user_id` — a regra do `0003`. No
`GUILD_CREATE` o `user_id` pode vir só dentro do `member`; quem monta
usa `member.user.id` como fallback, e sem os dois o estado é descartado
em vez de virar um objeto que não sabe de quem é.

### 6. O cache de voz entra na política

`CachePolicy.voice_states: bool = True`.

É `bool` (e não `int`) pela própria régua do `0008`: a entidade **tem
evento de remoção** — `VOICE_STATE_UPDATE` com `channel_id: null` é o
usuário saindo, e `GUILD_DELETE` limpa o guild inteiro.

Ligado por padrão porque o volume é a ocupação real de voz de um guild,
não a base de membros (`members` é opt-in porque `GUILD_CREATE` entrega
todo mundo de uma vez; voz entrega só quem está em canal). E é o único
caminho em que `voice_state_update -> (old, new)` não mente.

`ConnectionState` ganha `get_voice_state(guild_id, user_id)`; o updater
ganha `_voice_state_update`, e o `GUILD_CREATE` semeia a lista que o
payload já traz — sem semear, a primeira mudança de canal de um usuário
teria `old=None`.

### 7. Aridade estável quando o parser falha

O `0006` faz o parser falho entregar cru. Com dois argumentos, entregar
o dict cru **como argumento único** mudaria a aridade no meio do dispatch
— e o handler falharia com `TypeError` em vez do erro real.

Regra: a forma do payload é fixa, e o payload cru ocupa a **posição** do
modelo. `message_update` com parse falho entrega `(old, dict)`. Aridade
nunca muda; o tipo sim, e aí o handler reclama do atributo, que é o erro
verdadeiro.

### 8. `concurrent` espera

`0020` contra a ideia 10 §5. Vence o `0020`: um `TaskGroup` por dispatch
que espera todos dá cancelamento no shutdown sem código novo (o
`TaskGroup` é filho do dispatch, que é filho do Client). "Não espera"
seria `spawn` por handler, que é o `internal/tasks.py` — o usuário já
tem `ctx.spawn` para isso.

`sequential` continua o default (`K6`, fechado no `0009`).

### 9. `Client.dispatch(name, data)` — a notação `*args` do `0020` era ambígua

A finalidade escrita é "como o `FakeGatewayTransport` entrega sem tocar
na rede" — e o transport entrega `(nome, payload cru)`. Hook que aceitasse
argumentos interpretados **pularia** a instantânea e o updater, que são
justamente o que o `0020` acrescentou.

`async def dispatch(self, name: str, data: Any) -> None` é o `_dispatch`
tornado público: roda as cinco etapas. Um teste quer verificar o handler
manda o payload cru; quer verificar só o handler chama o dispatcher
direto, como já faz.

## Consequências

- `events/names.py` cresce cinco nomes: `message_delete_bulk`,
  `interaction_create`, `typing_start`, `voice_state_update` (e `resumed`
  já existe).
- `REGISTRY` ganha quatro parsers: `MESSAGE_DELETE_BULK` (vazio — a forma
  monta o par), `INTERACTION_CREATE`, `TYPING_START`, `VOICE_STATE_UPDATE`.
- `models/__init__.py` exporta `TypingStart` e `VoiceState`; a raiz
  junto.
- `state/event_updates.py` ganha `_voice_state_update` e a semeadura do
  `GUILD_CREATE`.
- Sete handlers existentes de `client.on` mudam de aridade. São os seis
  listados + `ready`/`resumed`, que **não** mudam por causa da correção.

## Quebras

| Evento | Antes (`client.on`) | Depois |
|---|---|---|
| `message_update` | `(Message,)` | `(Message | None, Message)` |
| `message_delete` | `(PartialMessage,)` | `(int, Message | None)` |
| `message_delete_bulk` | — | `(tuple[int, ...], tuple[Message | None, ...])` |
| `guild_update` | `(Guild,)` | `(Guild | None, Guild)` |
| `guild_delete` | `(PartialGuild,)` | `(int, Guild | None)` |
| `channel_update` | `(Channel,)` | `(Channel | None, Channel)` |
| `channel_delete` | `(PartialChannel,)` | `(int, Channel | None)` |

`ready` e `resumed` **não** mudam — é o objeto da correção §2.

`ids` e `olds` de `message_delete_bulk` são alinhados por índice:
`dict(zip(ids, olds))` funciona, e `olds` traz `None` onde o cache não
tinha a mensagem. Alinhar em vez de filtrar é o que permite saber qual
mensagem faltou.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `client.on` mantém um payload único (0006 intacto) | Duas tabelas para o mesmo evento; a API de baixo nível não veria o `old` |
| Aceitar `ready -> ()` e mexer nos testes | Seria o `0020` anulando o `0006` sem dizer; API de baixo nível sem o `Ready` |
| Deixar `typing_start`/`voice_state_update` de fora da tabela | A lista dos 15 é o contrato do `0020`; sair sem avisar é mudar decisão por implementação |
| Entregar `old=None` sempre em `voice_state_update` | A assinatura promete `VoiceState | None` e nunca devolve o primeiro — mentira silenciosa |
| `voice_states: int` com teto | A régua do `0008` diz `bool` para quem tem evento de remoção; e `0` significaria "desligado" |
| Parser falho entrega dict como argumento único | Mudaria a aridade no meio do dispatch — `TypeError` no lugar do erro real |
| `concurrent` não espera (ideia 10 §5) | Sem espera não há cancelamento no shutdown; `ctx.spawn` já é o caminho para não esperar |
| `client.dispatch(name, *args)` interpretados | Pulava a instantânea e o updater — o teste não testaria o que foi acrescentado |
| Validar anotação com igualdade estrita | Rejeitaria `Any`, alias e subtipo legítimos; a anotação é ganho de editor |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 19 Analista | Achou a contradição `0006` × `0020` na tabela do `ready` antes que ela virasse um bug de runtime |
| 06 Arquitetura | Uma tabela para as duas formas é a única em que validação de aridade significa a mesma coisa |
| 22 Contexto | `client.on` pior que `@event` seria a API de baixo nível virar o caminho de quem não quer saber |
| 17 Crítico | Contra entregar `old=None` sempre: "é uma assinatura que nunca devolve o primeiro valor" |
| 08 Segurança | Aridade estável é o que impede `TypeError` mascarar a falha real do parser |
| 09 Testes | Os testes e o smoke test são a prova de que `ready -> ()` era erro de documento, não de código |
| 11 Idiomático | `difflib` no nome de evento e `get_type_hints` leniente são o mesmo padrão dos `create_*` |
| 07 Concorrência | `TaskGroup` que espera é o que dá cancelamento de graça; não esperar é papel do `ctx.spawn` |
| 18 Pragmático | Modelos pequenos e mecânicos custam menos que uma tabela quebrada em dois lugares |
| 05 Hardware | Observou que a instantânea aloca uma tupla por evento com `old` — o `0020` já tinha preservado isso |

**Veredito do juiz: APROVADO COM AJUSTES.** O Juiz pediu que a correção
do `ready` ficasse escrita **na própria decisão**, e não só no commit —
contradição entre duas decisões resolve-se com um terceiro documento, não
com silêncio. Incorporado na §2 e na tabela "Quebras".

**Divergência preservada:** o Participante 18 (Pragmático) preferia adiar
`VoiceState` e `voice_states` para uma Fase 5, argumentando que nenhuma
ideia usa voz. Não prevaleceu porque a tabela dos 15 é do `0020` e o
custo é um modelo pequeno — mas fica registrado que o consumo real de
`voice_state_update` ainda não foi medido.

**Confiança: 84%.**
