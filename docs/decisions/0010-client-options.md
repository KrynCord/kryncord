# 0010 — Options e o construtor do `Client`

## Contexto

As ideias 02/11/12 propõem `CommandOptions`, `ResponderOptions` e
`EventOptions`, e um construtor do `Client` aberto para `token=`,
`intents=`, `registry=`, `commands=`, `responders=`, `events=`.

O construtor real é `Client(config: Config, *, transport_factory=...,
session_store=..., compression=..., http_transport=...)` — posicional,
e com quatro injeções de transporte que nada têm a ver com configuração.
Abrir para `token=`/`intents=` criaria dois caminhos para a mesma
coisa, e os dois precisariam continuar concordando para sempre.

## Decisão

### As Options são campos do `Config`

```python
@dataclass(frozen=True, slots=True)
class Config:
    ...
    commands: CommandOptions = field(default_factory=CommandOptions)
    responders: ResponderOptions = field(default_factory=ResponderOptions)
    events: EventOptions = field(default_factory=EventOptions)
```

`commands=`, `responders=` e `events=` como kwargs do `Client`
**não existem**. Um caminho só, e o mesmo de `cache=` e `http=` — já
construído, já testado, já congelado depois de construído.

O custo ergonômico é uma linha: `Config(commands=CommandOptions(...))`
no lugar de `Client(commands=CommandOptions(...))`. O ganho é que não
existe "qual dos dois venceu".

### `registry=` continua sendo kwarg do `Client`

Não é configuração, é **injeção** — o `K12` já decidiu que é o caminho
de teste. Injeção de dependência e configuração são coisas diferentes
e não podem dividir o mesmo lugar.

### Os três Options, com os tipos do `0009`

```python
class CommandOptions:
    default_member_permissions: Sequence[str | Permissions | int] | None = None
    guilds: Sequence[int] = ()
    middleware: ... = None
    on_error: ... = None
    on_not_found: ... = None
    verbose: bool = False


class ResponderOptions:
    middleware: ... = None
    on_error: ... = None
    on_not_found: ... = None


class EventOptions:
    middleware: ... = None
    on_error: ... = None
    dispatch_mode: Literal["sequential", "concurrent"] = "sequential"
```

`dm_permission` **não entra**: o campo existe no payload do Discord,
mas é `bool | None` com default `True`, e expor toda a tabela de campos
do payload como configuração é escorregar para "biblioteca é um dict
com atalhos". Quem precisa manda `raw=`.

### `CommandOptions.guilds` é `Sequence[int]`, não `str`

As ideias escreviam `Sequence[str]`. Snowflake é `int` desde o `0006`,
e `bool` é rejeitado antes de `int` — um guild id nunca é `True`.

`guilds` é o **escopo padrão** de quem não declarou `is_global` nem
`guild=` no decorator. `()` = padrão é global.

### `default_member_permissions` valida na construção

`__post_init__` do `CommandOptions`, levantando `DefinitionError` para
nome de permissão desconhecido. É validação de configuração, não de
definição de comando, e o erro tem que aparecer na linha do
`Config(...)`, não no `sync()`.

### Handlers continuam assíncronos obrigatoriamente

Inclusive comandos, responders, autocomplete e middleware — `TypeError`
no registro.

O `0009` fechou que `client.run(token)` existe (o ponto de entrada
síncrono). **Não** fez sync-handler virar permitido, e aqui fica
explícito que não vira. A regra do `0006` é uma só para a biblioteca
inteira: quem escreve handler escreve `async def`. `client.run` é
só `asyncio.run` com um nome melhor.

## Consequências

- `Config` cresce de 4 campos para 7. Continua frozen, continua slots.
- Todo teste que constrói `Config` continua igual — os novos têm default.
- A tabela de permissões ganha um dono: `commands/validation.py`,
  importado pelo `Config`.

## Escopo

`config.py` ganha os três dataclasses; `commands/options.py`,
`responders/options.py` e `events/options.py` **não existem** — as
Options moram com o resto da configuração.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `Client(commands=..., responders=...)` como atalho | Dois caminhos para o mesmo dado, e a divergência só aparece quando os dois discordarem |
| `Client(token=, intents=, config=)` | Derruba o construtor posicional atual e duplica o `Config` |
| `dm_permission` em `CommandOptions` | Expõe um campo do payload como configuração; `raw=` já cobre |
| Handlers síncronos | Contradiz o `0006`, e dois critérios de "handler válido" é confusão garantida |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 06 Arquitetura | Uma fonte de verdade para configuração ou duas que precisam concordar para sempre |
| 17 Crítico | O sketch das ideias contradiz o construtor real; quem copiar o sketch vai frustrar |
| 18 Pragmático | `Config(commands=...)` custa uma linha e remove uma classe inteira de bugs |
| 21 Advogado do diabo | Perguntou se a ergonomia de `Client(commands=)` valia a bifurcação; resposta: não, e a linha é mais explícita |
| 08 Segurança | `dm_permission` omitido é menos superfície para errar permissão |
| 22 Contexto | Snowflake é `int` — `Sequence[str]` herdava a confusão antiga |

**Veredito do juiz: APROVADO.** A decisão é a que remove superfície
em vez de adicionar.

**Divergência preservada:** o Participante 16 (Positivo) observou que
`Client(commands=...)` leria melhor em hello-world. Não mudou a
decisão — o README resolve o hello-world, não o construtor.

**Confiança: 92%.**
