# 0023 — Paridade da superfície de interação com o discord.js

## Contexto

Pedido explícito: **`responders/` tem que ser completo, com todos os
métodos do discord.js**.

O inventário foi feito no código de referência
(`base/discord.js`, v14.16.3), arquivo por arquivo. O que ele mostrou
não foi uma lacuna pequena — foi **quatro** lacunas de naturezas
diferentes, e uma delas já era um bug escondido:

| Arquivo de referência | Superfície | KrynCord antes |
|---|---|---|
| `interfaces/InteractionResponses.js` | 11 métodos de resposta | 7 (`reply`, `defer`, `edit`, `delete`, `follow_up`, `send_modal`, `ack`) |
| `BaseInteraction.js` | 21 `is_*()`/`in_*()` | 3 propriedades (`is_command`, `is_component`, `is_modal_submit`) |
| `AutocompleteInteraction.js` | `respond()`, `focused`, `responded` | API REST existe, **contexto não** |
| `CommandInteractionOptionResolver.js` | 13 getters | 4 (`get_string`, `get_int`, `get_float`, `get_bool`) |
| componentes (`MessageComponentInteraction`, `ModalSubmitInteraction`) | `values`, `fields`, `custom_id`, `message`, `component_type` | `custom_id` só |

### O bug encontrado no levantamento

`api/interactions.py::defer()` escolhe o tipo sozinho: componente vai
para `DEFERRED_UPDATE_MESSAGE`, o resto para
`DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE`. Na ramificação de componente,
`data` é `None` — ou seja, **`defer(ephemeral=True)` num botão descarta
a flag em silêncio**. O usuário pediu "só quem chamou vê" e não vê.

Isso é exatamente o padrão que o conselho já baniu duas vezes: silenciar
um pedido explícito.

## Decisão

### R1 — Três perguntas de defer, dois nomes

| Método | Pergunta | Tipo enviado |
|---|---|---|
| `defer(ephemeral=False)` | "quero tempo" | componente → `DEFERRED_UPDATE_MESSAGE`; senão → `DEFERRED_CHANNEL_MESSAGE` |
| `defer_update()` | "confirmar o clique sem mudar a mensagem" | `DEFERRED_UPDATE_MESSAGE`, sempre |

`defer_update()` **não** é sinônimo de `defer()`: são duas perguntas. O
`defer()` escolhe por tipo porque a intenção é "não deixa dar erro"; o
`defer_update()` é o handler de botão que sabe o que quer.

**`defer_reply()` não existe.** É `defer()` em interação que não é
componente — um terceiro nome para a mesma pergunta viola o `0012`.

**`defer(ephemeral=True)` sobre componente levanta `ValueError`.** O
Discord não aceita flags em `DEFERRED_UPDATE_MESSAGE`; descartá-las
silenciosamente é o bug que o levantamento encontrou. O caminho para
"pensando efêmero a partir de botão" é `defer_update()` +
`follow_up(ephemeral=True)`, que é o que o follow-up existe para.

`defer_update()` em interação que não é componente →
`InteractionStateError`, com a saída na mensagem.

### R2 — `update()` e `fetch_reply()` entram no `InteractionContext`

O `0012` já nomeou o `InteractionContext` como dono de responder.
`update()` é a resposta mais usada de botão — sem ela, todo handler de
botão reescreveria o mesmo `callback(7, …)` na mão.

- `update(content=None, **kwargs)` — aceita vazio. Diferente de
  `reply()`, que recusa `ValueError` em payload vazio: `update()` sem
  nada significa "mantém como está", que é o ack de componente.
- `fetch_reply(message_id=None)` — delega ao `original_response()`, que
  já existe e já trata o 404 como `None`.
- `delete(message_id=None)` — `None` apaga a original (comportamento
  atual); um id apaga um follow-up.
- `defer`/`update`/`fetch`/`delete` ganham o retorno `Message | None`
  onde a API já devolve — hoje `edit()` e `delete()` descartam.

### R3 — `launch_activity()` entra; collectors não

`launch_activity()` é uma linha sobre `callback()` com
`InteractionResponseType.LAUNCH_ACTIVITY = 12`. Custo irrisório, e é um
método real do mixin. Entra, com a ressalva no docstring de que o app
precisa ter atividade habilitada.

`awaitModalSubmit()` **não** vira `InteractionCollector`. A ideia `07`
§6 já registrou a armadilha (o `on_not_found` dispara para interação que
um collector estava observando) e a recomendação de projeto é "não use
collectors; registre um `@responder` com rota".

O que entra no lugar é o que resolve o caso de uso real — mostrar modal
e esperar o submit **inline**:

```python
await ctx.send_modal(form_modal())
sub = await ctx.await_responder("/register/form", timeout=300)
```

`await_responder(custom_id, *, timeout)` é single-shot, observa o
dispatch e **não consome** ele: o `@responder` correspondente roda
normalmente, `on_not_found` não muda, e o futuro resolve com o valor de
retorno do `run(ctx)` (transporte por retorno, `0022`). Sem filtro, sem
`max`, sem `collect` — o resto do `InteractionCollector` fica para depois
de houver um caso concreto.

### R4 — `ResponderType` é `StrEnum`

A ideia `07` escreve `ResponderType.STRING_SELECT` e
`ResponderType.MODAL`. Colocar isso num `IntEnum` colide:

```
ComponentType.USER_SELECT      = 5
InteractionType.MODAL_SUBMIT   = 5
InteractionType.AUTOCOMPLETE   = 4
ComponentType.TEXT_INPUT       = 4
```

Um `IntEnum` único obrigaria a mapear dois namespaces discordantes num
só, e a colisão faria `types=[ResponderType.MODAL]` casar com
`TEXT_INPUT` — falha silenciosa, no registro, sem erro em lugar nenhum.

`StrEnum` elimina a colisão por construção, degrada bem em mensagem de
erro (`'FOO' is not a valid ResponderType`) e é escrito uma vez por
responder. É a mesma régua que o `K2` usou para `cache=` — ali o
`StrEnum` foi recusado por verbosidade num argumento repetido; aqui a
alternativa é **errada**, não verbosa.

Valores: `ACTION_ROW`, `BUTTON`, `STRING_SELECT`, `TEXT_INPUT`,
`USER_SELECT`, `ROLE_SELECT`, `MENTIONABLE_SELECT`, `CHANNEL_SELECT`,
`MODAL_SUBMIT` (+ alias `MODAL`), `AUTOCOMPLETE`.

### R5 — Os `is_*()` vão para o modelo `Interaction`

São predicados puros de `type` + `data.component_type` + `data.type` —
não têm estado, não têm I/O, não dependem do contexto. Colocá-los num
contexto os tornaria indisponíveis para quem só tem o payload (cache,
teste, logger).

Os nomes vêm das **ideias**, não do discord.js: `is_string_select()`,
não `isStringSelectMenu()`. O `0012` manda um nome por pergunta.

**Correção registrada:** a ideia `07` §2 e §4 escrevem
`interaction.is_modal()`. O modelo já tem `is_modal_submit` (e o
`07` §3 tabela já diz "MODAL (alias de MODAL_SUBMIT)"). Dois nomes para
a mesma coisa é exatamente o que o `0012` baniu — **`is_modal_submit()`**
é o nome, `is_modal()` não existe.

Superfície, 17 métodos: `is_autocomplete`, `is_command`,
`is_chat_input_command`, `is_context_menu_command`,
`is_user_context_menu`, `is_message_context_menu`,
`is_message_component`, `is_modal_submit`, `is_button`,
`is_select_menu`, `is_string_select`, `is_user_select`,
`is_role_select`, `is_channel_select`, `is_mentionable_select`,
`is_repliable`, `in_guild`.

São **métodos**, não propriedades — mesmo nome do discord.js, mesmo
custo de chamada, e `if ctx.interaction.is_button()` lê como pergunta.
Os três que já existem como propriedade (`is_command`, `is_component`,
`is_modal_submit`) viram métodos; **era uma divergência interna**: o
`is_command` propriedade e o `is_chat_input_command()` método não
respondiam a mesma pergunta com a mesma forma.

### R6 — `ResponderContext` é o objeto entregue ao handler

A ideia `07` nomeia o primeiro parâmetro de `interaction`, e o `0012`
diz que é `ResponderContext`. São o mesmo objeto: o contexto **compõe**
o modelo (`ctx.interaction`) e **proxya** o que se escreve mais perto do
código do handler.

| Grupo | Onde vive | No contexto |
|---|---|---|
| resposta | `InteractionContext` | `reply`, `defer`, `defer_update`, `update`, `edit`, `delete`, `follow_up`, `fetch_reply`, `send_modal`, `ack`, `await_responder`, `is_responded` |
| rota | `responders/context.py` | `custom_id`, `params`, `values`, `fields` |
| tipo | `models/interaction.py` | `is_*()` (via `ctx.interaction.is_*()` **e** proxy) |
| dados | `commands/context.py` já tem | `guild`, `channel`, `member`, `user`, `client`, `state`, `spawn` |

`fields` é `ModalFields`: `.get_text_input(id)`, `.keys`, `[]`, `in`.
`values` é `tuple[str, …]` — tupla, não `list`: o Discord entrega uma
lista e ninguém deveria conseguir "append" em valores que já chegaram.

### R7 — `AutocompleteContext` existe e não tem `reply`

Já decidido no `0012` ("autocompete só responde com escolhas"), mas o
tipo não foi escrito. Ele tem `focused` (propriedade, `0012`),
`respond(choices)`, `options`, `state`, `spawn` — e **não** `reply`,
`defer` nem `edit`. `responded` acompanha o estado.

### R8 — Getters que faltam no `OptionsAccessor`

`get_subcommand`, `get_subcommand_group`, `get_number`, `get_user`,
`get_member`, `get_role`, `get_channel`, `get_attachment`,
`get_mentionable`.

Os quatro últimos resolvem por `data.resolved` — o mesmo achado do
`0008`: `Member`/`Role` não têm `guild_id`, e quem sabe a guild é quem
leu o evento. O accessor já recebe a `Interaction` inteira, então lê
`resolved` direto, sem novo contexto.

## Consequências

- `defer(ephemeral=True)` em componente **passa a quebrar** onde antes
  falhava silenciosamente. É intencional e é o ponto da decisão — mas é
  uma mudança de comportamento e precisa aparecer no changelog.
- `ResponserType` em `StrEnum` significa que `types=[3]` (o número cru)
  não funciona. Ninguém escreve isso, e aceitar causaria o mesmo erro
  silencioso da colisão.
- `await_responder` acopla o `dispatch.py` a uma lista de esperas. É a
  primeira dependência "de trás para frente" — o handler espera pelo
  próximo dispatch. Restrição: a espera tem que ser cancelada no
  shutdown, senão vira task órfã.
- O modelo `Interaction` cresce de 3 para 17 predicados. Todos são
  `return self.type == …` — zero complexidade, e o custo é legibilidade
  do arquivo, não de execução.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Um só `defer()` com auto-detecção e sem `defer_update()` | Some a pergunta "confirmar sem mudar"; handler de botão rápido teria que entender a tabela de tipos |
| `defer(ephemeral=True)` em componente só ignora a flag | Foi o bug encontrado; silenciar pedido explícito é o padrão já bani duas vezes |
| `ResponderType(IntEnum)` mapeando os dois namespaces | Colisão `5=5` e `4=4` — casaria modal com text input, sem erro em lugar nenhum |
| `is_*()` no contexto e não no modelo | Inacessível para quem só tem o payload (cache, teste, logger) |
| `is_modal()` como nome curto junto de `is_modal_submit()` | Dois nomes para uma pergunta, o `0012` já baniu |
| `InteractionCollector` genérico | `07` §6 já registrou a armadilha do `on_not_found`; `max`/`filter`/`collect` não têm caso concreto ainda |
| `ResponderContext` herdar `InteractionContext` | Já rejeitado no `0012`: compor, não herdar — um só dono do estado |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 17 Crítico | Levantou o `defer(ephemeral=True)` silencioso — era um bug, não uma lacuna, e é o achado mais caro do documento |
| 06 Arquitetura | `is_*()` no modelo porque são predicados do payload; contexto que os reexporta é convenância, não dono |
| 01 Simplicidade | Contra `defer_reply()`: a pergunta "quero tempo" já tem dono |
| 11 Idiomático | `StrEnum` no `ResponderType` com o argumento de que a alternativa não é verbosa, é **errada** |
| 09 Testes | Os três caminhos de `defer()` (comando, componente, componente+ephemeral) são determinísticos e baratos |
| 07 Concorrência | `await_responder` só é seguro se a espera for cancelada no shutdown — registrado como restrição |
| 02 Performance | 17 predicados `==` não movem agulha; o `lru_cache` dos hints do `0014` continua sendo o único hot path do roteador |
| 18 Pragmático | Contra adiar `update()`: é o método mais usado de botão, e adiar o bloco inteira deixa a superfície meio construída |
| 05 DX | Nomear o parâmetro do handler `interaction` (como as ideias) ou `ctx` (como o `0012`) — resolvido: é o mesmo objeto, e o docstring mostra os dois |

**Veredito do juiz: APROVADO COM AJUSTES.** Os ajustes: (a) registrar a
quebra de comportamento do `defer(ephemeral=True)` em componente no
changelog, (b) corrigir `is_modal()` → `is_modal_submit()` nas ideias
na hora de escrever os docstrings, (c) `await_responder` com
cancelamento no shutdown desde o primeiro dia.

**Divergência preservada:** o Participante 19 (Analista) discordou de
`launch_activity()` entrar sem que haja como testá-lo ponta a ponta —
não há atividade habilitada no bot de teste. Ficou registrado que o
método é coberto por teste de **chamada** (o `type` enviado), não de
efeito.

**Confiança: 87%.**
