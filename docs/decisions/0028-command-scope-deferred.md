# 0028 — Escopo do `@command` quando o decorator não declara

## Contexto

`0009` K1 fechou que o decorator aceita `is_global=` e `guild=`, e que
**nem um dos dois** significa o default de `CommandOptions`. `0010`
completou: "`guilds` é o **escopo padrão** de quem não declarou
`is_global` nem `guild=` no decorator. `()` = padrão é global."

O Bloco 8 é o primeiro a implementar `create_command`, e a frase não tem
dono. Três candidatos, e nenhum serve como está:

| Onde resolver | Por que não |
|---|---|
| No `create_command` | Ele não tem o `Config`. `@command` roda no **import** do módulo de usuário, que pode ser anterior ou posterior à construção do `Config` |
| No `Config.__post_init__` | Escreveria num registry global a partir da construção de um objeto — mutação global implícita, e ordem-de-import viraria comportamento |
| No `sync()` | `CommandSync.__init__(registry, applications)` não recebe `Config`, e `registry.for_scope()` lê a **chave** já gravada — expandir depois exigiria um segundo accessor de instâncias |

E o campo não é teórico: `CommandOptions(guilds=(1, 2))` é construído e
coagido em teste, e **não é lido por ninguém** em `src/`. Um knob
declarado que ninguém consome é pior que um knob inexistente: ele
parece funcionar.

O obstáculo de ordem é real. No fluxo padrão:

```python
config = Config(commands=CommandOptions(guilds=(DEV,)))
client = Client(config)  # <- registry vazio: bootstrap ainda não rodou
await bootstrap("mybot.commands.**")  # <- os @command rodam aqui
await client.start()
```

`Client.__init__` é **cedo demais** para re-chavear, e `create_command`
é **cedo demais** para perguntar. O primeiro momento em que `Config`,
registry preenchido e importações concluídas coexistem é `start()`.

## Decisão

### 1. O decorator resolve o que ele sabe; o resto fica marcado

```python
create_command(name=..., is_global=None, guild=None)
```

| Declaração | Escopo registrado | `deferido` |
|---|---|---|
| `guild=123` / `guild=(123, 456)` | `(123,)` / `(123, 456)` | não |
| `is_global=True` | `(None,)` | não |
| `is_global=False` sem `guild` | `CommandDefinitionError` | — |
| `is_global` e `guild` juntos | `CommandDefinitionError` (`0009` K1) | — |
| **nenhum declarado** | `(None,)` | **sim** |

O `deferido` é um `bool` na `CommandInstance`. O registro é idêntico ao
caso global — a chave é a mesma, e nada que lê chave enxerga diferença.
A diferença é só para quem pergunta.

`is_global=False` sem `guild` é erro porque o comando não iria a lugar
nenhum: registraria num escopo inexistente e o `sync` o enviaria para
`list_commands(None)`, que é a rota global.

### 2. `Client.start()` re-chaveia os adiados

```python
self._registry.commands.reescopiar(self._config.commands.guilds)
```

`reescopiar(escopos)` move toda instância `deferida` para as chaves de
`escopos`. Com `guilds=()` (o default), é **no-op**: `()` significa
"padrão é global", e a instância já está no global — o `None` que o
decorator registrou é exatamente a resposta certa.

É chamado no `start()` porque é o primeiro ponto garantidamente posterior
ao `bootstrap` no fluxo padrão. Registrar **depois** do `start()` deixa a
instância no global, e é aceito: é o mesmo comportamento de hoje, e a
alternativa (re-chavear a cada registro) faria o `Config` do primeiro
`Client` decidir para sempre.

### 3. Nada no registry muda

`scopes()`, `for_scope()` e `instances()` continuam derivados da chave
(`0026` §2). O `reescopiar` é o único caminho que move chave, e é
explicitamente chamado — não há observador vendo o registry mudar
"sozinho".

## Consequências

- `CommandInstance` ganha `deferido: bool` e `escopos: tuple[int | None, ...]`.
- `CommandRegistry` ganha `reescopiar(escopos)` e `register` passa a
  aceitar vários escopos para a mesma instância (`0026` §2).
- `CommandOptions.guilds` deixa de ser declarado-e-não-lido.
- Um `Client` por processo com `guilds` diferentes re-chaveia duas vezes;
  a segunda não encontra adiados e é no-op. `0009` já aceitou
  registry compartilhado como risco conhecido em teste, mitigado por
  `Client(registry=...)`.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Resolver no `create_command` lendo o `Config` | `Config` não existe no import, e a ordem de import passaria a decidir comportamento |
| `Config.__post_init__` escrevendo no registry global | Mutação global implícita a partir de um construtor de dado |
| Resolver no `sync()` | `CommandSync` não recebe `Config`, e `for_scope` lê a chave já gravada — exigiria um segundo accessor só para isto |
| Não implementar, deixar `guilds` como está | Um knob que parece funcionar e não funciona é pior que não ter |
| `create_command(globals=Config(...).commands.guilds)` | Devolve o problema ao usuário, que era exatamente o que o `K1` queria evitar |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 19 Analista | Levantou que `guilds` não tinha leitor em `src/` — o campo era a prova de que a pergunta existia antes do código |
| 01 Simplicidade | "Re-chaveia no `start()`" é 12 linhas e torna verdade uma frase escrita em `0010`; a alternativa é uma fase nova de registro |
| 06 Arquitetura | A ordem de import não pode decidir escopo de registro — é o mesmo argumento do `0027` contra auto-correção de import circular |
| 11 Idiomático | `deferido` no registro e `reescopiar` explícito mantêm o registry como dado puro: nada muda sem alguém chamar |
| 17 Crítico | Apontou que `is_global=False` sem `guild` registraria em escopo nenhum e o `sync` mandaria para a rota global em silêncio |
| 09 Testes | `Client(registry=Registry())` já é a mitigação do `0009`; o `reescopiar` no `start()` não cria risco novo em teste porque testes de unidade não chamam `start()` |
| 07 Concorrência | Re-chavear no `start()` é antes de qualquer task — não há dispatch observando metade do registry |
| 08 Segurança | `guilds=()` como no-op preserva o comportamento de todo bot existente: nada muda para quem não configurou |
| 18 Pragmático | Duas chamadas (init e sync) foram consideradas e descartadas: `sync` sem `padrao` explícito re-chavearia de volta ao global |

## Veredito do juiz: APROVADO

O juiz pediu que ficasse explícito que `reescopiar` **não** é caminho
de API pública — é chamado pelo `Client`, e chamar de fora em teste
sem um `Config` correspondente é montagem de estado inválida.

## Divergência preservada

O Participante 20 (Visionário) propôs que o decorator aceitasse
`config=` opcional, resolvendo tudo no registro. Não entrou: é uma
superfície nova que resolve um problema de uma linha e obriga todo
módulo de comando a importar o `Config` — e o `Config` é do aplicativo,
não do módulo.

## Confiança: 82%
