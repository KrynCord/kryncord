# 0026 — Ponto de entrada de comandos e roteamento de `INTERACTION_CREATE`

## Contexto

Os blocos 3, 4 e 5 construíram a maquinaria de comandos, interações e
responders, e cada um terminou no seu próprio fim: `CommandInstance`,
`CommandContext`, `dispatch_responder` e `dispatch_autocomplete` existem,
e **nenhum deles tem chamador**.

O levantamento para o bloco 8 achou cinco lacunas que nenhuma decisão
registrou como pendente:

| Lacuna | Decisão que a criou |
|---|---|
| `@command` / `create_command` não existe | ideia 03 §1, ideia 02 §2 |
| Nada roteia `INTERACTION_CREATE` | ideia 07 §7, e o `0021` que escreveu "o `interaction_create` do `0020` precisa distinguir `type=8`" |
| `CommandInstance.run(ctx)` não existe | `0022` — "é o que o dispatcher chama" |
| `Client(registry=...)`, `client.run()`, `client.commands` | `0009` K12, K8; `0019` §Retorno |
| `ctx.spawn()` falha num `Client` real | `0012` — os contextos procuram `client._tasks`, e o `Client` não tem esse slot |

A quinta é um bug latente: os contextos procuram `client._tasks` (um
`TaskRegistry`, criado pelo `0012` justamente porque o `TaskGroup` do
`Lifecycle` **cancela a task pai** quando uma filha falha). O `Client`
só tem `_lifecycle`. Todo `ctx.spawn()` em produção levanta
`RuntimeError` com a mensagem de "contexto montado à mão".

E o `0017` definiu middleware e `on_error` de comando — que não têm
onde morar, porque não existe despacho de comando.

## Decisão

### 1. `@command` e `create_command` em `commands/decorators.py`

```python
@command(
    name="ping",
    description="Responde com pong",
    type=ApplicationCommandType.CHAT_INPUT,
    is_global=True,  # K1 — default
    guild=123,  # K1 — uma guild
    guild=(123, 456),  # K1 — várias guilds
    options=(...),
    middleware=...,
    on_error=...,
)
async def ping(ctx: CommandContext) -> None: ...
```

`on_not_found=` **não** entra aqui: ele é pergunta do `Options` ("eu
não conheço este nome"), e uma `CommandInstance` só existe se o nome
for conhecido — ver `0030`.

Dois níveis, como a ideia 02 §2 pede: `create_command(**kwargs)` devolve
`CommandInstance` (é o que `0011` decidiu que `create_command` devolve) e
`command(**kwargs)` é o decorador, que devolve a **função original** —
trocar o objeto da função por uma instância quebraria `@command` acima
de `@staticmethod`, `functools.wraps` e introspecção de teste.

Validação na importação, mesmo critério do resto: `name` vazio, tipo sem
`description`, opção duplicada, handler síncrono (`TypeError`, `0010`).

`registry=` é o parâmetro de teste dos dois (K12). Sem ele, o global.

### 2. `guild=(a, b)` registra a mesma instância sob cada escopo

`CommandDefinition.scope` continua `int | None` — o `0011` fechou que não
há value object, e a URL não tem terceiro escopo. O registry passa a
guardar por **chave**, não por valor:

- `scopes()` deriva de `{k[2] for k in _por_chave}` (era `{i.scope ...}`);
- `for_scope(s)` filtra pela chave (era pelo `instance.scope`);
- `instances()` deduplica por identidade — um comando em duas guilds é
  um comando, não dois, e o `load_logs` do `0027` conta instâncias.

A instância retorna o **primeiro** escopo em `.scope`. Nada de despacho
lê `.scope` (o despacho lê a chave), e a alternativa — N instâncias
compartilhando um mutável — faria `.sub()` num guild afetar só a
primeira.

### 3. `CommandInstance.run(ctx)` é o contrato, e a cadeia é por nível

`0022`, tabela inteira. `run(ctx)` executa **este nível** e devolve o
valor; o dispatcher injeta como segundo parâmetro no nível seguinte.

```
command.run(ctx)  ->  grupo.run(ctx, valor)  ->  sub.run(ctx, valor)
```

Cada nível é opcional. Um comando simples tem só `command.run`.

| Situação | Comportamento |
|---|---|
| Filho não declara o parâmetro | valor descartado |
| Filho anota `T` e recebe `U` | `DispatchError` |
| Filho anota `T | None` e recebe `None` | ok |
| Filho anota `*args: Any` | aceita qualquer coisa |
| Filho não anota | aceita (com o aviso de que `mypy` perde o ganho) |

A checagem é `get_type_hints` + `isinstance`, como a ideia 04 §4 pede —
`get_type_hints` uma vez por registro, cacheado, não por dispatch.

`_Grupo` ganha `__call__` para registrar o handler do **grupo** (a ideia
04 §4 mostra `@group()` transformando o valor). Sem handler de grupo, o
valor do comando pai vai direto ao subcomando.

### 4. `interactions/dispatch.py` roteia por tipo — a ordem da ideia 07 §7

```text
INTERACTION_CREATE
 ├─ APPLICATION_COMMAND            -> commands/dispatch.py
 ├─ APPLICATION_COMMAND_AUTOCOMPLETE -> commands/autocomplete.py
 ├─ MESSAGE_COMPONENT              -> responders/dispatch.py
 ├─ MODAL_SUBMIT                   -> responders/dispatch.py
 └─ (sem handler no tipo)          -> on_not_found do tipo correspondente
```

Um módulo só, com `dispatch_interaction(interaction, api, *, ...)` —
quatro chamadores seriam quatro lugares para a mesma ordem mudar.

`on_not_found` é o do `Options` correspondente: o de comandos para
`APPLICATION_COMMAND`, o de responders para os outros dois.

### 5. O roteamento roda **antes** dos handlers de `@event("interaction_create")`

```
1. instantânea
2. updater
3. ready
4. roteamento de interação   <- novo
5. handlers de evento
```

É a mesma lógica do "cache antes dos handlers" (`0008`): o roteamento é
o que **responde dentro de 3 segundos**, e um handler de observação que
rodasse primeiro consumiria essa janela. Quem registra
`@event("interaction_create")` para logar vê o estado da resposta já
adiantado — o que é mais informativo, não menos.

A alternativa (handlers primeiro) daria ao observador a chance de
responder *e* ao roteamento a de responder de novo — duas respostas para
uma interação, que o Discord recusa com 400 e o usuário vê "algo deu
errado".

### 6. `ctx.state` nasce no `_dispatch` e é compartilhado

O `0012` diz literalmente "criado por dispatch". Hoje cada contexto
cria o seu — o que dá o mesmo resultado enquanto um dispatch toca um
só contexto, e deixa de dar quando `INTERACTION_CREATE` alimenta o
roteamento **e** os handlers de evento.

`_dispatch` cria `state: dict[str, Any] = {}` e o repassa. Os contextos
ganham `state=` como parâmetro keyword, com `{}` como default — os
testes que montam contexto à mão continuam iguais.

### 7. `Client._tasks = TaskRegistry()`

Criado no `__init__`, cancelado no `_shutdown` **antes** do Lifecycle.

Ordem importa: uma task de fundo com requisição em voo é cancelada
primeiro, e só então o `TaskGroup` do Lifecycle sai — o contrário deixaria
o `cancela_todas` rodando num grupo que já está fechando.

É o que faz `ctx.spawn()` funcionar num `Client` real, que é o que o
`0012` prometeu.

### 8. `Client(registry=...)` e `client.commands` / `client.responders`

K12 e o `0019`. `registry=` default é o global de `kryncord.registry`;
`client.commands` devolve o `CommandRegistry` e `client.responders` o
`ResponderRegistry`.

Sem isso, `client.commands.instances()` — a forma que o `0019` escolheu
no lugar de um objeto de relatório — não existe, e o `bootstrap` do
bloco 9 não teria o que contar.

### 9. `client.run(token)` (K8)

`asyncio.run` com um nome melhor, e com a checagem que o `0009` pediu:
chamado dentro de um loop já rodando, levanta `LifecycleError` com a
mensagem apontando `await client.start()`. Rodar e estourar depois é o
caso de notebook e de framework — e o erro sai mais barato que o
traceback.

`run()` preenche `Config.token` se estiver vazio. `Config` é frozen, então
recebe um `replace` — mesma dataclass, um objeto novo.

### 10. Middleware: global de `Options` **mais** por entrada

`0017` escreveu "middleware por comando ou por handler não existe na
1.0". A metade "por comando" já está construída do outro lado: o
`@responder(middleware=...)` existe, está testado, e o
`ResponderEntry.middleware` é lido no despacho.

Duas superfícies diferentes para a mesma pergunta é pior que uma
corrigida. Então:

| Nível | Comandos | Responders | Eventos |
|---|---|---|---|
| Global (`Options`) | ✅ | ✅ | ✅ |
| Por entrada (decorator) | ✅ `@command(middleware=)` | ✅ já existe | ✅ `@event(middleware=)` |
| Por handler (dentro de um) | ❌ | ❌ | ❌ |

A proibição do `0017` vale para o **terceiro** nível, que é o que
"dobraria registro, validação e precedência". Os dois primeiros são um
`tuple` concatenado na mesma ordem, e a precedência é a mesma em todos:
global primeiro, depois o da entrada.

A cadeia de eventos é a mesma: `compose` serve para juntar vários numa
`Options`, porque a `Options` aceita **uma** função por tipo.

### 11. Os três `on_error` default

| Tipo | Default |
|---|---|
| Comando | loga; se `not ctx.is_responded()`, tenta **uma** efêmera e engole o erro dela |
| Responder | já existe (`responders/dispatch.py::_erro`) — mesma forma |
| Evento | só loga: `EventContext` não tem `reply` (`0012`) |

`BlockHandlers` é capturado **antes** do `except Exception` nos três
despachos: é a única exceção controlada, e chegando no `on_error` viraria
"falha" um bloqueio que foi tratamento (`0017`).

### 12. `loop.set_exception_handler` instalado no `start()`, restaurado no `close()`

`0017` pediu para pegar o erro típico de `asyncio.create_task` sem
`await` e apontar `ctx.spawn` na mensagem.

Instalado no `start()` e **restaurado** no `close()`: o handler é global
por loop, e uma biblioteca que instala em `__init__` e nunca devolve
deixa a mensagem dela no processo mesmo depois do bot fechar. Restaurar
é devolver o que se pegou.

Não substitui o comportamento — só reformula a mensagem.

## Consequências

- `commands/` ganha `decorators.py` e `dispatch.py`; `interactions/`
  ganha `dispatch.py`.
- `CommandInstance` ganha `run()` e `_Grupo.__call__`.
- `CommandRegistry` passa a derivar `scopes()`/`for_scope()` da chave.
- `Client.__slots__` cresce `_registry` e `_tasks`.
- `tests/conftest.py` ganha a fixture de `Client(registry=...)` que o
  `0009` listou como mitigação do risco "registry global esconde estado
  em teste".
- `dispatch_responder` e `dispatch_autocomplete` finalmente ganham
  chamador.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `command` devolve a `CommandInstance` | Trocar o objeto da função quebra `@staticmethod`, `wraps` e teste que inspeciona a função |
| Uma instância por escopo, com `_rebuild` em cascata | `.sub()` num escopo afetaria os outros por acidente, e a sincronia só se manteria se ninguém esquecesse |
| Handlers de evento rodam antes do roteamento | Consumiria a janela de 3s e abriria a dupla resposta |
| `ctx.state` por contexto (como está) | Um dispatch de interação toca dois contextos — o `0012` diz "por dispatch" |
| `Lifecycle.spawn` no lugar do `TaskRegistry` | O `TaskGroup` cancela o pai quando o filho falha — é a razão do `0012` ter criado o `TaskRegistry` |
| Só middleware global (ler o `0017` ao pé da letra) | O `@responder(middleware=)` já existe e está testado; duas superfícies para a mesma pergunta |
| `set_exception_handler` em `__init__` | Deixaria a mensagem da biblioteca no processo depois do `close()` |
| Roteador em quatro lugares (um por tipo) | Quatro lugares para a mesma ordem mudar |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 19 Analista | O levantamento achou cinco lacunas de decisão fechada sem implementação — a lista, não o código, era o que faltava |
| 06 Arquitetura | Um módulo de roteamento só: a ordem da ideia 07 §7 é uma ordem, não quatro |
| 22 Contexto | Roteamento antes dos handlers é a mesma razão do "cache antes dos handlers" — é tempo, não preferência |
| 07 Concorrência | `TaskRegistry` no `Client` é o que o `0012` já tinha decidido; achar o `RuntimeError` valia o bloco |
| 17 Crítico | Apontou que ler o `0017` ao pé da letra faria a biblioteca ter uma superfície de middleware para responder e outra para comando |
| 11 Idiomático | `command` devolver a função é o contrato Python para decorador; o resto é convenção que se quebra em silêncio |
| 09 Testes | A fixture de `Client(registry=...)` estava listada desde o `0009` como mitigação — e nunca existiu |
| 18 Pragmático | `get_type_hints` cacheado por registro é o custo zero no dispatch que a ideia 04 já pedia |
| 08 Segurança | Restaurar o exception handler é devolver o que se pegou; biblioteca que não devolve deixa lixo no processo |
| 01 Simplicidade | `run(ctx)` por nível é o contrato que o `0022` já escreveu — nada novo foi inventado aqui |

**Veredito do juiz: APROVADO COM AJUSTES.** O Juiz pediu que a correção
do `0017` (middleware por entrada existe) ficasse explícita **dentro da
tabela de níveis**, e não só na prosa — é a parte que alguém vai ler
depressa. Incorporado na §10.

**Divergência preservada:** o Participante 20 (Visionário) propôs um
`client.dispatch_interaction()` público para quem quer interceptar antes
do roteamento. Não entrou — `client.dispatch(name, data)` do `0025` já
cobre o caminho inteiro, e dois hooks seriam dois contratos para o mesmo
momento.

**Confiança: 86%.**
