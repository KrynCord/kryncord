# 0011 — Registry de comandos

## Contexto

As ideias divergem sobre a chave do registry:

- 02 §8 e 04 §5: `(name, escopo)`
- 05 §5: `(type, name, scope)` — "menu e slash não colidem"

E divergem sobre o retorno de `create_command`: 02 §2 mostra
`CommandDefinition`, 04 §3 mostra `CommandInstance` com `.group()`.

Como `K1` introduziu escopo por guild, a chave de duas pontas ainda
fica curta: o mesmo nome em duas guilds são dois comandos.

## Decisão

### A chave é `(type, name, scope)`

```python
CommandKey = tuple[ApplicationCommandType, str, int | None]
```

Um USER menu chamado `ping` e o slash `/ping` são dois comandos
distintos no Discord — colidiriam numa chave de duas pontas e o
registry recusaria um registro legítimo.

### `scope` é `int | None`

`None` = global. Um inteiro = o id da guild.

Não há value object nem enum: são duas pontas, e o `int | None` é o
que o payload e a URL já usam. Um `CommandScope` inventado teria que
ser traduzido de volta em `None | int` no momento de montar a rota.

### `create_command` devolve `CommandInstance`

Resolve 02 §2 × 04 §3. `CommandDefinition` é o que a propriedade
`.definition` devolve — o dado enviado ao Discord, e não o objeto que
o usuário encadeia `.group()`.

### Import duplicado é silencioso; definição conflitante é erro

| Situação | Comportamento |
|---|---|
| Mesmo `(type, name, scope)`, payload igual | Devolve a instância já registrada, silenciosamente |
| Mesmo `(type, name, scope)`, payload diferente | `CommandDefinitionError` apontando os dois módulos |

A fronteira é a comparação do payload. `bootstrap` + import direto do
`command.py` é o caso normal e não pode reclamar; dois módulos
contestando o mesmo nome é o caso que reclama.

A mensagem precisa citar os dois locais — sem isso, o erro não diz
onde procurar.

### O registry guarda autocomplete no `CommandInstance`

`{option_name: Callable}`, mais `"*"` para a função genérica. Nenhuma
estrutura paralela no registry: o autocomplete pertence ao comando.

### API do registry

```python
class CommandRegistry:
    def register(self, instance: CommandInstance) -> CommandInstance: ...
    def get(self, type, name, scope) -> CommandInstance | None: ...
    def instances(self) -> tuple[CommandInstance, ...]: ...
    def for_scope(self, scope) -> tuple[CommandInstance, ...]: ...
```

Quatro métodos. `for_scope` é o que `sync()` usa para agrupar por
destino, e é o motivo de o escopo estar na chave e não num atributo
secundário.

### Grupo sem subcommand falha antes de qualquer requisição

`sync()` valida **todas** as definições antes de montar a primeira
payload. Um grupo vazio derruba o sync inteiro, com o nome do grupo,
em vez de mandar um comando inválido e esperar o 400.

A validação fica na construção da payload, não na criação do comando —
o grupo pode ser declarado antes de os subcommands serem registrados.

## Consequências

- O registry é um `dict` de quatro entradas por comando; em 1000
  comandos isso é 1000 entradas, e a lookup é O(1).
- `for_scope` devolve tupla — ordenação é responsabilidade do `sync`,
  que ordena por nome para o diff ser estável.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Chave `(name, scope)` | USER menu `ping` colidiria com `/ping`, que são dois comandos legítimos |
| `CommandScope` value object | Precisaria ser traduzido de volta em `None | int` para a URL e o payload |
| Singleton por `(name, scope)` | Ignora o `type`; mesmo problema da chave de duas pontas |
| Erro em qualquer re-registro | Derrubaria `bootstrap` + import direto, que é o caminho normal |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 06 Arquitetura | A chave é o contrato; errar nela custa muito mais que errar num método |
| 19 Analista | Apontou que 05 §5 já dizia `(type, name, scope)` e as outras duas ideias encurtavam |
| 22 Contexto | No Discord, `type` é parte da identidade do comando — USER e CHAT_INPUT nunca colidem lá |
| 01 Simplicidade | `int | None` no lugar de um objeto que só traduz de volta |
| 17 Crítico | Perguntou sobre o singleton silencioso: dois módulos com o mesmo nome e payloads diferentes é erro real, e a comparação é o teste |
| 08 Segurança | Mensagem de erro com os dois módulos é o que impede alguém perseguir o lugar errado |

**Veredito do juiz: APROVADO.**

**Divergência preservada:** o Participante 20 (Visionário) preferia
`CommandScope` para poder crescer (ex: escopo de DM). Não prevaleceu:
Discord não tem terceiro escopo, e adicionar depois é compatível.

**Confiança: 90%.**
