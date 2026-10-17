# Métodos de resposta a interação

A superfície de resposta, sua ordem legal e o erro que cada violação
produz. O estado é a máquina do `InteractionContext` (`0016`,
completada no `0031`); a arquitetura das classes está em
[interactions-architecture.md](interactions-architecture.md).

O princípio: **a sequência errada é erro nosso** —
`InvalidInteractionState`, com a ação e o estado na mensagem — e não um
400 genérico do Discord que não diz qual chamada saiu fora de hora.

## Estados

| Estado | Significado |
|---|---|
| `UNANSWERED` | nada foi mandado ainda |
| `DEFERRED` | defer reconhecido — "pensando…" na tela |
| `ANSWERED` | resposta inicial entregue |
| `MODAL_OPENED` | modal aberto — **terminal**: o envio é uma interação nova |
| `COMPLETED` | resposta original apagada — só follow-up resta |
| `EXPIRED` | token vencido (15 min) — nenhum callback funciona mais |

`EXPIRED` é calculado com preguiça a partir do snowflake da interação:
`criado + 15 min < agora`. Não há timer. Ids sintéticos de teste (menores
que a época do Discord) nunca expiram. A propriedade `state` devolve o
estado *efetivo* (com `EXPIRED`); os predicados `is_responded()` etc.
leem o estado interno — expirar não apaga o que já aconteceu.

## Métodos

Todos em `BaseInteraction`, salvo onde indicado:

| Método | O que faz | De onde sai |
|---|---|---|
| `respond(content, ...)` | resposta inicial | `UNANSWERED` |
| `defer(ephemeral=False)` | adia a resposta | `UNANSWERED` |
| `defer_update()` | confirma o clique sem mudar a mensagem | `UNANSWERED` (**componentes**) |
| `update(content, ...)` | substitui a mensagem do componente | `UNANSWERED` (**componentes**) |
| `edit_original_response(content, ...)` | edita a resposta original | `DEFERRED`, `ANSWERED` |
| `delete_original_response()` | apaga a resposta original | `DEFERRED`, `ANSWERED` |
| `fetch_original_response()` | busca a resposta original | qualquer estado válido |
| `followup(content, ...)` | mensagem extra no mesmo webhook | depois da resposta inicial |
| `open_modal(modal)` | abre um modal | `UNANSWERED`, `DEFERRED` |
| `ack()` | garante acknowledge — no-op se já garantiu | qualquer |
| `launch_activity()` | abre a Activity vinculada | `UNANSWERED` |
| `autocomplete(choices)` | sugestões do autocomplete | `AutocompleteInteraction` |

`defer_update` e `update` existem **só** em `ComponentInteraction` — num
comando, chamá-las é `InvalidInteractionState` explicando isso.
`AutocompleteInteraction` tem só `autocomplete()`.

## Transições

```text
UNANSWERED ──respond──────────────▶ ANSWERED
UNANSWERED ──defer/defer_update/ack─▶ DEFERRED
UNANSWERED ──update/launch_activity▶ ANSWERED
UNANSWERED ──open_modal───────────▶ MODAL_OPENED  (terminal)

DEFERRED ──edit_original_response──▶ ANSWERED
DEFERRED ──delete_original_response▶ COMPLETED
DEFERRED ──open_modal──────────────▶ MODAL_OPENED

ANSWERED ──edit_original_response──▶ ANSWERED      (idempotente)
ANSWERED ──delete_original_response▶ COMPLETED

MODAL_OPENED ──ack (no-op)────────▶ MODAL_OPENED
COMPLETED    ──ack (no-op)────────▶ COMPLETED
EXPIRED      ── nada ─────────────▶ (sem transição)
```

`followup()` não transiciona: ele é proibido em `UNANSWERED` e
permitido depois — inclusive de `COMPLETED`, porque um follow-up é
*outro* webhook message, não a resposta original.

`ack()` nunca falha por estado: reclamar que já foi acknowledge seria
dizer que o chamador errou por ter atingido o objetivo.

## Erros

### `InvalidInteractionState`

Levantada quando a ação não existe a partir do estado atual. A mensagem
nomeia os dois — a ação, o estado, e a saída possível:

```text
respond() não é permitido depois de ANSWERED — responda com
edit_original_response() ou delete_original_response(), ou use
followup() ...
```

Com token vencido, a mensagem muda de assunto: não é ordem, é prazo —
*nenhum* callback funciona mais.

### `ValueError` e `RuntimeError`

| Caso | Erro |
|---|---|
| `defer(ephemeral=True)` em componente | `ValueError` — `DEFERRED_UPDATE_MESSAGE` não aceita flags; use `defer_update()` + `followup(ephemeral=True)` |
| interação montada à mão sem `api` | `RuntimeError` com o que falta |
| resposta falhou na API | a exceção propaga e o estado **não** avança — o retry funciona |

## Exemplos

```python
from kryncord import ButtonInteraction, CommandInteraction, button, command


@command(name="ping", description="Responde pong")
async def ping(interaction: CommandInteraction) -> None:
    await interaction.respond("pong")


@button("atualizar")
async def atualizar(interaction: ButtonInteraction) -> None:
    await interaction.defer_update()          # clique reconhecido
    await interaction.followup("atualizado", ephemeral=True)
```

```python
# responda rápido, finalize depois — o clássico "pensando…"
await interaction.defer()
await database.consultar()
await interaction.edit_original_response("pronto")
```

```python
# modal: terminal — a submissão é uma interação nova, com @modal_submit
await interaction.open_modal(create_modal("Pedido", [create_text_input("item")]))
```
