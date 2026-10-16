# 0017 — Middleware, tags, `block` e hierarquia de erros

## Contexto

A ideia 11 é a que mais se contradiz com as demais:

- 11 §3: "`block()` impede o `run`, mas **não** impede o `on_not_found`"
- 11 §3 também: "`block()` aborta a cadeia"
- 10 §4: "erro em um handler **não** impede os demais" (modo sequencial)

E três nomes para a mesma exceção aparecem: `DefinitionError`,
`BlockHandlers`, `BlockHandlerException`.

## Decisão

### Middleware é assíncrona, obrigatoriamente

`TypeError` no registro — o mesmo critério dos handlers do `0006`.
Middleware que precisa de I/O (verificar permissão remota, cachear) é
assíncrona por natureza.

### Assinatura única: `fn(ctx, block)`

As três ideias tinham assinaturas diferentes —
`(ctx, block)` em comando, `(interaction, block, params)` em responder,
`(ctx, block)` em evento. Unificadas:

```python
async def command_middleware(ctx: CommandContext, block) -> None: ...
async def responder_middleware(ctx: ResponderContext, block) -> None: ...
async def event_middleware(ctx: EventContext, block) -> None: ...
```

`ctx` carrega o que cada uma precisa (`.interaction`, `.params`,
`.client`). Um parâmetro a menos, e `block` **sempre** é o segundo.

### `block()` aborta middleware **e** handlers — e também `on_not_found`

Resolve 11 §3. Se você bloqueou, você tratou. Deixar o `on_not_found`
rodar depois de um bloqueio faria o tratamento padrão responder a uma
interação que a middleware já assumiu.

`BlockHandlers` é a exceção que `block()` levanta; o dispatcher a captura
**antes** de chegar ao `on_error`. É a única exceção controlada do
despacho.

### Só uma exceção: `BlockHandlers`

`BlockHandlerException` e o `DefinitionError` usado como nome de block
ficam abandonados. Definição e bloqueio são coisas diferentes, e
`DefinitionError` já existe com outro significado (`0009`).

Exportado da **raiz** (`from kryncord import block, BlockHandlers`): a
função é pública, a exceção que ela levanta tem que ser capturável.

### Exceção em middleware ≠ block

| Situação | O que acontece |
|---|---|
| `block()` chamado | `on_error` **não** roda; handlers e `on_not_found` rodam não |
| Middleware levanta exceção | `on_error` roda, middleware seguinte **e** handler não rodam |
| Handler levanta exceção (modo `sequential`) | `on_error` roda; próximo handler roda |

Três casos, três comportamentos. A 11 §3 misturava o primeiro com o
segundo.

### `compose(*fns)` exporta da raiz, implementa em `internal/compose.py`

Resolve a tensão arquivo × raiz: o arquivo é interno (não faz parte da
superfície), o nome é público. `from kryncord import compose`.

Uma middleware por tipo em Options — `compose` para várias. Middleware
**por comando** ou **por handler** não existe na 1.0: não há caso de uso
nas ideias, e dobraria a superfície (registro, validação, precedência).

### Tags só existem em eventos

00-INDEX §1. Comandos e responders não têm tags na 1.0.

### Hierarquia de erros — tudo em `errors.py`

Nada em `commands/errors.py`: um só lugar, como já é para `HTTPError`,
`GatewayError` etc.

```
KrynCordError
├── DefinitionError                    (0009 — definição inválida)
├── CommandDefinitionError             (0009 — definição de comando)
├── ResponderDefinitionError           (0009 — rota/conversor)
├── EventDefinitionError               (0009 — nome de evento)
├── DispatchError                      (novo — falha de despacho)
│   ├── BlockHandlers                  (novo — capturado pelo dispatcher)
│   └── ConversionError                (novo — conversor falhou)
├── ComponentError                     (novo — montagem de componente)
├── InteractionStateError              (novo — transição inválida)
├── InteractionTimeoutError            (novo — token expirou)
├── RateLimitError                     (existe)
├── LifecycleError                     (existe)
├── HTTPError / RESTError              (existe)
└── GatewayError / GatewayFatalError   (existe)
```

`ConversionError` dentro de `DispatchError` porque é uma falha de
despacho; `ComponentError` fora porque montar componente não é despacho.

### `on_error` default: loga, e responde só se ainda dá

```python
get_logger(__name__).error("Erro em %s", nome, exc_info=True)
if ctx.is_responded() is False:
    await ctx.reply("...", ephemeral=True)  # tenta UMA vez
```

Se a resposta de erro **também** falhar (token expirado, 400), loga e
engole — nunca uma exceção sem tratador no meio de um despacho.

### `loop.set_exception_handler` é instalado pelo `Client`

Para pegar o erro típico de `asyncio.create_task` sem `await` e
apontar `ctx.spawn` na mensagem. Não substitui o handler, apenas
reformula.

## Consequências

- `errors.py` cresce de 13 para 17 classes; a tabela do topo é a única
  referência
- O dispatcher ganha um `except BlockHandlers` explícito **antes** do
  `try/except Exception` dos handlers
- `internal/compose.py` é o primeiro arquivo de `internal/` que a raiz
  reexporta

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `block()` deixa `on_not_found` rodar (11 §3) | Responderia a uma interação que a middleware já assumiu — dois tratamentos para o mesmo evento |
| Middleware por comando na 1.0 | Sem caso de uso nas ideias; dobra registro + validação + precedência |
| `commands/errors.py` separado | Duas árvores de erro para a mesma biblioteca |
| `BlockHandlers` chega no `on_error` | O dispatcher é o único que sabe que foi bloqueio, não falha |
| Tags em comandos e responders | Nenhuma ideia as usa; é inventar API |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 19 Analista | A 11 §3 era literalmente autocontraditória — "impede o run" e "não impede o on_not_found" no mesmo parágrafo |
| 08 Segurança | Dois tratamentos para o mesmo evento é o caminho para resposta dupla |
| 06 Arquitetura | Uma árvore de erros em `errors.py` é a única forma de `except KrynCordError` significar alguma coisa |
| 09 Testes | Os três casos (block / exceção em middleware / exceção em handler) são distinguíveis só porque a hierarquia separa `BlockHandlers` |
| 01 Simplicidade | Assinatura `(ctx, block)` nos três tipos remove um parâmetro e uma decisão |
| 21 Advogado do diabo | Contra unificar assinaturas: o responder precisava de `params`; resposta — `ctx.params` já existe |
| 12 Alto desempenho | `compose` com duas funções é um `for`; sem abordagem extra |

**Veredito do juiz: APROVADO COM AJUSTES.** O Juiz pediu que `compose`
não virasse uma classe — ficou como função simples. Incorporado.

**Divergência preservada:** o Participante 18 (Pragmático) preferia
adiar `on_error` default para depois, argumentando que log já basta.
Não prevaleceu porque a interação ficaria sem resposta visível e o
usuário acharia que o bot travou.

**Confiança: 90%.**
