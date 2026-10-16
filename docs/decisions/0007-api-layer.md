# 0007 — Camada `api/`: vocabulário sobre a mecânica REST

**Data:** 2026-10-11
**Status:** aceita

## Contexto

A Fase 1 entregou `RESTClient`: fila, bucket, rate limit, retry,
leitura de erro. Tudo isso é **mecânica** — existe uma vez, para todo
endpoint. O que faltava era o **vocabulário**: o que significa mandar
uma mensagem, e como o chamador escreve isso.

Sem a camada, `Client` não tinha REST nenhum. Um bot recebia eventos e
não conseguia responder — observava, mas não agia.

## Decisão

### `api/` é a fachada por recurso; `rest/` continua sendo a mecânica

`api/` tem nove módulos — `messages`, `channels`, `members`, `roles`,
`webhooks`, `applications`, `interactions`, `guilds`, `users` — cada um
delegando para `RESTClient`. Nenhum módulo de `api/` reimplementa
transporte, rate limit ou retry — a `0001` já decidiu isso, e duplicar
seria a segunda fonte de verdade que sai de sincronia.

### Modelos continuam sendo dados puros

A pergunta que mais aparece: por que `client.api.messages.reply(m, ...)`
e não `message.reply(...)`, como em `discord.py` e `discord.js`?

A resposta é que **`Message` é `frozen=True, slots=True`**. Não muda,
não tem comportamento, e é construível num teste com
`Message.from_payload({...})` sem existir nenhum `Client` no processo.
Injetar o cliente nele transformaria o modelo em dependência de estado
de runtime — e o teste que quer só verificar parsing teria que construir
um bot primeiro.

O custo é uma palavra a mais por chamada. O ganho é que a `0003` segue
sendo verdadeira: dado puro, imutável, testável sozinho.

`message.reply()` pode vir depois como açúcar por cima disto, sem
quebrar nada — é aditivo, não alternativa.

### Os métodos aceitam ID **ou** objeto

`api.messages.send` aceita ``123``, ``"123"``, `Channel`,
`PartialChannel` ou a própria `Message`. `api.messages.reply` aceita
`Message`, `PartialMessage` ou um ID — e descobre o canal pelo objeto.

Dez linhas em `api/_resolve.py`, e o chamador não precisa decorar qual
método quer int e qual quer objeto.

Para `edit`/`delete`/`pin`/`unpin` com ID puro existe ``channel=``: um
``int`` não carrega canal, e mandar para o canal errado daria um 404
apontando "mensagem não encontrada" — a resposta errada para o problema
real.

### Resposta que não vira modelo é `HTTPError`

`Model.from_payload` devolve `None` quando falta o campo essencial. Isso
está certo para Gateway — entrega-se o dict cru e o handler decide.

Para REST é errado. O chamador fez `await`, esperou uma `Message`, e
`None` empurraria uma decisão que ninguém escreveu para o código dele —
e esconderia que o Discord devolveu algo que não era o que pedimos.

Então `api/_parse.py` levanta `HTTPError` com a rota na mensagem.

### `Config.token` vazio vira `Token | None`, não `Token("")`

Com `Token("")`, o header sairia ``Authorization: Bot `` — malformado.
O Discord responderia 401 apontando para o token, e quem lê o erro
correria para rotacionar um token que nunca esteve errado.

Com `None`, `HTTPClient.build_headers` recusa antes de mandar, com
`HTTPError("Requisição autenticada sem token configurado")`. Diz o que
falta, no lugar certo.

## Consequências

- `Client.api` existe desde a construção, não só depois do `start()`:
  REST e Gateway são independentes (ver `0004`), e um handler registrado
  fora do `async with` ainda captura `client.api` no closure.
- `Client.close()` e `__aexit__` fecham o pool HTTP, não só o Gateway.
  Um pool aberto segura socket.
- Ordem de shutdown: Gateway → tasks → HTTP. O HTTP vai por último
  porque um handler cancelado no meio pode ter requisição em voo, e
  fechar o pool antes daria erro de transporte no lugar do
  `CancelledError` que o chamador espera.
- Sem `Message.clean_content`, `Channel.send()`, `Message.reply()`: o
  açúcar sobre modelo entra quando houver cache para sustentá-lo.

## Escopo

O recorte inicial (17 métodos, 4 módulos) seguiu a regra da `0003`:
entra quando um endpoint concretamente precisar. O que mudou foi o
critério de "concretamente precisar". Um bot que **não consegue listar
as últimas mensagens de um canal** não é um bot com escopo justo — é um
bot cortado. E sem `applications`/`interactions` não existe `/comando`,
que é o que a Fase 4 pede.

Hoje, **70 métodos em 9 módulos**:

| Módulo | Endpoints |
|---|---|
| `messages` | send, reply, fetch, edit, delete, pin, unpin, add_reaction, remove_reaction, remove_all_reactions, remove_all_reactions_for |
| `channels` | fetch, modify, delete, typing, create, list_messages, delete_messages, create_thread, join_thread, leave_thread, list_thread_members, list_active_threads, list_archived_threads |
| `members` | list, fetch, add, edit, remove, ban, unban, bans, fetch_ban |
| `interactions` | callback, respond, defer, update_message, pong, show_modal, autocomplete, original_response, edit_original, delete_original, followup |
| `applications` | me, list_commands, fetch_command, create_command, edit_command, delete_command, bulk_overwrite_commands |
| `roles` | list, fetch, create, edit, delete, add_to_member, remove_from_member |
| `webhooks` | list, fetch, create, edit, delete, execute, execute_slack |
| `guilds` | fetch, modify, leave |
| `users` | me, fetch |

`discord.js` tem 236 em 18 módulos — mas o `core/src/api/` dele é
gerado de `discord-api-types`, que por sua vez é gerado do spec
OpenAPI. É uma tabela de rotas com nome. Cada um destes 70 foi escrito
à mão, e cada um valeu uma decisão de API: aceita objeto? devolve
modelo? o que faz quando falta campo?

Ficou de fora, e continua sendo nicho de verdade: `monetization`,
`oauth2`, `roleConnections`, `soundboardSounds`, `stageInstances`,
`poll`, `invite`, `sticker`, audit log, emojis. Entra quando um uso
concreto exigir.

### Modelos novos

`Role`, `Ban`, `Webhook`, `ApplicationCommand` e `Interaction` entraram
pelo mesmo motivo da `0003`: sem eles a camada devolveria dict — e
prometer modelo para devolver ``dict`` é prometer o que não se entrega.

Dois casos merecem nota:

- **`Webhook.token` é `str | None`, não `str = ""`** —
  `GET /webhooks/:id` não entrega token. Ausente e vazio não são a
  mesma coisa: o primeiro não foi entregue, o segundo seria um token
  que não serve para nada.
- **`Interaction` não tem `responded`** — um atributo que alguém
  esquece de marcar mente. O Discord não devolve se já respondemos, e
  o estado real existe do lado de quem respondeu, não no objeto.

### Três bugs que os testes pegaram

Valem registro porque nenhum teria aparecido ao vivo em desenvolvimento:

1. **`original_response` não devolvia `None` em 404.** O
   `if response.status == 404` era código morto — `RESTClient` converte
   4xx em `DiscordAPIError` *antes* de devolver a `Response`. O 404
   tinha que ser pego da exceção.
2. **`_emoji_segment` quebrava as duas formas de emoji custom.** O
   formato é `<:name:id>` e `<a:name:id>`; tirar só os ``<>`` sobrava
   `:name:id` (dois-pontos na frente) e `a:name:id`. E o separador de
   animação é `a:` com dois-pontos, não `a_`.
3. **`reason="   "` virava `X-Audit-Log-Reason: %20%20%20`** — entrada
   de auditoria em branco, pior que nenhuma. A normalização é da
   `api/`, não do transporte: o transporte manda o que recebe.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `message.reply()` carregando o bot | Modelo deixa de ser dado puro; teste de parsing precisaria construir um `Client`. |
| Só aceitar ID | O chamador decoraria qual método quer int e qual quer objeto. |
| Devolver `None` quando não parseia | Empurra uma decisão não escrita para o código de quem usa, e esconde resposta inesperada da API. |
| Validar payload antes de enviar | Duplicaria a tabela do Discord, que muda; e a mensagem de erro do Discord aponta o campo. |
| `Token("")` para token vazio | Header malformado, 401 que aponta para o lugar errado. |

## Referências

- `KrynCord-ARCHITECTURE.md` §`api/`
- `docs/decisions/0001-http-transport.md` — a mecânica por baixo
- `docs/decisions/0003-data-models.md` — por que modelos são dados puros
- `docs/decisions/0004-build-order.md` — REST e Gateway independentes
- `docs/decisions/0006-event-dispatch.md` — o outro lado do ciclo
