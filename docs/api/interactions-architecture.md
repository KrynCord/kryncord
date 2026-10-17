# Arquitetura de interações tipadas

Como o KrynCord entrega interações ao código da aplicação desde o
`0031`: **sem `ctx` genérico**. O handler recebe a classe da interação
que ele registrou — `CommandInteraction`, `ButtonInteraction`,
`ModalSubmitInteraction`… — e a classe vem do registro, nunca da
anotação.

Este documento é a referência da superfície. O *porquê* está no
[ADR 0031](../decisions/0031-typed-interactions.md); a máquina de
resposta, em [interaction-response-methods.md](interaction-response-methods.md).

## As camadas

| Camada | Arquivo | Papel |
|---|---|---|
| Payload | `models/interaction.py` | `Interaction` — `frozen`, dado puro do Discord |
| Estado | `interactions/response.py` | `InteractionContext` — dono da máquina de estados (interno) |
| Base | `interactions/base.py` | `InteractionBase` (payload, cache lazy, `spawn`) e `BaseInteraction` (métodos de resposta) |
| Tipadas | `interactions/commands.py`, `components.py`, `autocomplete.py` | as classes que o handler vê |

O handler **nunca** vê o `InteractionContext`: ele vê a interação
tipada, que delega para o dono do estado. O estado não mora no modelo —
`Interaction` é `frozen` (`0003`), e o mesmo payload pode alimentar mais
de um contexto durante um dispatch.

## As classes

### Comandos (`kryncord.interactions.commands`)

| Classe | Comando | Atributos próprios |
|---|---|---|
| `CommandInteraction` | `CHAT_INPUT` (`/ping`) | `.options` (OptionsAccessor), `.command_name` |
| `UserCommandInteraction` | menu de usuário | `.target_user`, `.target_member` |
| `MessageCommandInteraction` | menu de mensagem | `.target_message` |
| `EntryPointInteraction` | `PRIMARY_ENTRY_POINT` (Activities) | — |

### Componentes (`kryncord.interactions.components`)

Todos herdam de `ComponentInteraction`, que herda de `BaseInteraction`:

| Classe | Registrada por |
|---|---|
| `ButtonInteraction` | `@button`, `@responder(types=[BUTTON])` |
| `StringSelectInteraction` | `@string_select` |
| `UserSelectInteraction` | `@user_select` |
| `RoleSelectInteraction` | `@role_select` |
| `ChannelSelectInteraction` | `@channel_select` |
| `MentionableSelectInteraction` | `@mentionable_select` |
| `ModalSubmitInteraction` | `@modal_submit` |

Atributos do `ComponentInteraction`: `.custom_id`, `.params` (params da
rota), `.values`, `.fields` (`ModalFields`), `.message`; métodos próprios
`.update(...)`, `.defer_update()`, `.await_responder(...)`.

### Autocomplete (`kryncord.interactions.autocomplete`)

`AutocompleteInteraction` herda só de `InteractionBase` — não tem
`respond` nem `open_modal`. Tem `.focused` (nome da opção), `.focused_value`
(o que o usuário digitou), `.options`, e o único método de resposta:
`.autocomplete(choices)`.

## A entrega é determinística

A classe entregue ao handler vem **do decorator/registry**, nunca da
anotação lida do handler. A anotação é conferida contra a entrega — não
decide a entrega:

| Registro | Classe entregue |
|---|---|
| `@command` (CHAT_INPUT) | `CommandInteraction` |
| `@command(type=USER)` | `UserCommandInteraction` |
| `@command(type=MESSAGE)` | `MessageCommandInteraction` |
| `@command(type=PRIMARY_ENTRY_POINT)` | `EntryPointInteraction` |
| `@inst.autocomplete(...)` | `AutocompleteInteraction` |
| `@button` / `@responder(types=[BUTTON])` | `ButtonInteraction` |
| `@modal_submit` | `ModalSubmitInteraction` |
| `@responder` com vários tipos | `ComponentInteraction` (a classe comum) |

## Validação na importação

O primeiro parâmetro do handler é obrigatoriamente anotado, e a
anotação tem que bater com o que será entregue. Falhou, é
`HandlerSignatureError` **na linha do decorator** — nunca um
`TypeError` no primeiro clique:

```python
@button("fortalecer")
async def clicou(interaction: ButtonInteraction) -> None:
    await interaction.respond("ok")

@button("fortalecer")
async def clicou(interaction) -> None: ...   # HandlerSignatureError: sem anotação
@modal_submit("caixa")
async def enviou(interaction: ButtonInteraction) -> None: ...  # erro: entrega ModalSubmitInteraction
```

Regras, num sítio só (`internal/signatures.py`):

- **Anotação obrigatória.** Sem ela, editor e mypy não veem o contrato.
- **Classe esperada ou subclasse** — `ComponentInteraction` registrado
  com `types=[BUTTON, MODAL_SUBMIT]` aceita `ButtonInteraction`.
- **União** aceita quando *todos* os membros são aceitáveis
  (`CommandInteraction | None` de quem escreve defensivo).
- **`Any` e protocolo passam** — não dá para conferir com `issubclass`,
  e inventar regra seria mais errado que aceitar.
- **`object` não passa** — é classe, e classe que não é a entregue está
  dizendo que o handler recebe outra coisa.
- `*args` no primeiro lugar não conta como primeiro parâmetro.

## Roteamento

`INTERACTION_CREATE` entra em `interactions/dispatch.py` e sai por um
de quatro ramos (`0026` §4):

```text
INTERACTION_CREATE
 ├─ APPLICATION_COMMAND              -> commands/dispatch.py
 ├─ APPLICATION_COMMAND_AUTOCOMPLETE -> commands/autocomplete.py
 ├─ MESSAGE_COMPONENT                -> responders/dispatch.py
 ├─ MODAL_SUBMIT                     -> responders/dispatch.py
 └─ (sem handler no tipo)            -> on_not_found do tipo correspondente
```

## Sintaxe de rota (`0031`)

O `custom_id` é roteado por segmentos (`/`), e o parâmetro é `{}`:

```text
/manage/user/{user_id}/{action}   literal, param, param
/page/{?number}                   {?param} — opcional
/giveaway/**                      wildcard no fim, casa 0 ou mais
/giveaway/**{args}                wildcard nomeado, casa 1 ou mais
/produto:{product_id}:comprar     param embutido no segmento
```

- `{param}` exige pelo menos um caractere; o valor não pode conter `/`
  (que é o separador de segmento).
- `{?param}` ausente **omite o segmento inteiro** — `/a/{?x}` com `x`
  faltando é `/a`, não `/a/`.
- Params embutidos casam contra o texto do segmento com regex
  não-ganancioso: em `produto:{id}:comprar`, o id de
  `produto:12:34:comprar` é `12:34`.
- A sintaxe antiga (`:param`, `?:param`, `**:nome`) **não existe mais**:
  `parse_rota` recusa com `ResponderDefinitionError` citando a troca.

Constrói-se com `build_custom_id`, que valida o que o Discord não
validaria (parâmetro ausente, valor vazio, `/` no valor, mais de 100
caracteres):

```python
from kryncord import build_custom_id

build_custom_id("/manage/user/{user_id}/{action}", user_id=123, action="ban")
# "/manage/user/123/ban"
build_custom_id("/produto:{product_id}:comprar", product_id=42)
# "/produto:42:comprar"
```

## Registradores e decoradores

```python
from kryncord import (
    button, channel_select, mentionable_select, modal_submit,
    responder, role_select, string_select, user_select,
)
from kryncord.enums import ResponderType
```

Todos os decoradores de componente são açúcar sobre `@responder`, que
valida a assinatura, classifica a rota e registra no `ResponderRegistry`
— conflito de padrão com tipos sobrepostos é erro **na importação**
(`0013`).

## Eventos

`@event` e `client.on` entregam **só o payload** (`0031`):

```python
from kryncord import event
from kryncord.models import Message

@event("message_create")
async def visto(message: Message) -> None: ...
```

O quadro interno do dispatch (`EventFrame`) não é exportado: ele mora
em `kryncord.events.context` e chega só à middleware (`fn(frame, block)`)
e ao `on_error` (`fn(frame, exc)`), que precisam do nome do evento, do
client e do estado compartilhado — e são mecanismos internos, não a
superfície que o autor do bot escreve.
