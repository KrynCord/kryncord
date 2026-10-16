# 0022 — Context menus e transporte de dados entre níveis

## Contexto

A ideia 05 descreve context menus (USER/MESSAGE) e a 04 §4 descreve como
um grupo passa dado de um nível ao próximo. As duas estão ligadas pelo
mesmo mecanismo — `CommandInstance.run()` — e decidir uma sem a outra
deixaria o contrato incompleto.

## Decisão

### Context menu é `@command(type=...)`

```python
@command(type=ApplicationCommandType.USER)
async def menu(ctx: CommandContext) -> None: ...


@command(type=ApplicationCommandType.MESSAGE)
async def copiar(ctx: CommandContext) -> None: ...
```

Sem sintaxe nova. O `type` já existe no decorator (`0009`), e o
`K1` já decidiu que a chave é `(type, name, scope)`.

### Validação por tipo, em `commands/validation.py`

| Tipo | Regra |
|---|---|
| `CHAT_INPUT` | `description` obrigatória (1–100); `options` ≤ 25 |
| `USER` | **sem** `description`, **sem** `options` |
| `MESSAGE` | **sem** `description`, **sem** `options` |

O Discord recusa as duas últimas com 400 se forem enviadas. Validar
antes é o mesmo princípio do `0018` — falhar na importação, não na
requisição.

A mensagem cita o tipo e o nome do comando.

### `ctx.target_*` só em context menu

```python
ctx.target_user  # USER
ctx.target_member  # USER, se o cache tiver
ctx.target_message  # MESSAGE
ctx.target_channel  # MESSAGE, se houver
```

`AttributeError` em `CHAT_INPUT`. São quatro atributos, não um dict —
cada um é uma pergunta diferente.

### Transporte de dados entre níveis

Regra mantida da 04 §4, com os detalhes fechados:

| Situação | Comportamento |
|---|---|
| `run(ctx)` devolve valor | injetado como **segundo** parâmetro do subcommand |
| Tipo checado | `get_type_hints` + `isinstance` em runtime |
| Subcommand omite o parâmetro | valor é descartado |
| Anotado `T` e recebe `U` | `DispatchError` |
| Anotado `T \| None` e recebe `None` | ok |
| Anotado `T \| U` | aceita os dois |
| Anotado `*args: Any` | aceita qualquer coisa |

`DispatchError` (do `0017`) porque é falha de despacho, não de
definição — a definição estava certa, o valor é que não bate.

### Duas formas de passar dado, com fronteira clara

| Mecanismo | Alcance | Dono |
|---|---|---|
| Retorno de `run(ctx)` | entre **níveis** de um mesmo dispatch | `CommandInstance` |
| `ctx.state["k"]` | entre **dispatches** | `EventContext` / middleware |

A 04 §4 só descrevia a primeira; a 10 §2 só a segunda. Elas não
concorrem: uma atravessa a hierarquia, a outra atravessa o tempo.

### `CommandInstance.run` é o contrato

É o que o dispatcher chama depois de resolver o caminho. A assinatura é
fixa, e o valor devolvido é o cano de dados — não há um segundo mecanismo.

## Consequências

- `commands/validation.py` cresce a validação por tipo, junto do resto
- O dispatcher de comando precisa suportar injeção do segundo parâmetro
- `ctx.target_*` é atributo dinâmico: ou quatro propriedades, ou um
  `__getattr__` — decisão de implementação, não de contrato

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `@user_command` / `@message_command` separados | Três decoradores para o que é um parâmetro |
| `ctx.target` como dict | Quatro perguntas diferentes viram chaves de string, sem erro de digitação |
| Injeção por nome do parâmetro | Mais mágico; segundo parâmetro posicional é o que Python já faz |
| Uma forma só de transporte | A hierarquia e o tempo são problemas diferentes; fundir exigiria um mecanismo que cobre mal os dois |
| Validar no sync | Mesmo custo de rede do `0018`; validação local é de graça |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 22 Contexto | `USER`/`MESSAGE` no Discord não têm options nem description — a validação é o contrato do payload |
| 19 Analista | As duas formas de transporte não concorrem; fronteira clara evita "por que meu dado não chegou" |
| 06 Arquitetura | `CommandInstance.run` é um contrato só, e o dispatcher não precisa saber mais nada |
| 11 Idiomático | Segundo parâmetro posicional é a injeção que o Python já tem |
| 09 Testes | Tabela de seis linhas para o transporte é exatamente o número de casos |
| 18 Pragmático | Reusar `@command(type=...)` custa zero API nova |

**Veredito do juiz: APROVADO.**

**Divergência preservada:** o Participante 16 (Positivo) queria
`ctx.target_attachment` para menu de mensagem — o Discord não entrega
anexo no alvo, só a mensagem; quem quer o anexo lê
`ctx.target_message.attachments`. Fica registrado.

**Confiança: 93%.**
