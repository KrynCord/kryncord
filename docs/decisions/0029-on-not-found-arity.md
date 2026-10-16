# 0029 — Assinatura do `on_not_found`

## Contexto

`0010` tipou os dois `on_not_found` de `Options` como `ErrorHandler`:

```python
ErrorHandler = Callable[[Any, BaseException], Awaitable[None]]  # (ctx, error)
```

O Bloco 8 implementou os dois caminhos e eles **não concordam**:

```python
# commands/dispatch.py :: _nao_encontrado
await on_not_found(ctx, None)  # 2 argumentos

# responders/dispatch.py :: dispatch_responder
await _chama(on_not_found, ctx)  # 1 argumento
```

O teste `test_on_not_found_de_comando_nao_vai_para_responder` escreveu
o handler como `async def h(ctx, nome)` seguindo a anotação de
`config.py` — e o ramo de responder levantou
`TypeError: missing 1 required positional argument`.

Ou seja: a anotação de um lado, a implementação do outro, e nenhum
teste cobrindo o lado de comando. O sintoma clássico de duas metades
escritas em momentos diferentes.

A pergunta é qual dos dois é o contrato.

## Decisão

### 1. Um argumento só: `on_not_found(ctx)`

As **três** fontes independentes dizem uma:

| Fonte | O que escreve |
|---|---|
| `ideias/02-creators.md` §6 | `async def command_on_not_found(ctx: CommandContext) -> None` |
| `ideias/11-middleware-opcoes.md` §5 | `async def command_on_not_found(ctx: CommandContext)` e `async def responder_on_not_found(interaction)` |
| `ideias/exemplos/bot_configurado.py` | `async def on_command_not_found(ctx: CommandContext)` e `async def on_responder_not_found(interaction)` |
| `src/` (responder) | `_chama(on_not_found, ctx)` — 1 argumento, e tem teste passando |
| `src/` (comando) | `on_not_found(ctx, None)` — 2 argumentos, e **não tem teste nenhum** |

O segundo argumento é sempre `None`. `on_not_found` significa "ninguém
atendeu" — não é falha, não há exceção para passar. Um parâmetro que
nunca pode ter outro valor não é informação, é um incumbente: obriga
todo usuário a escrever um argumento que ele nunca vai ler, e quebra
qualquer handler escrito conforme a documentação.

`config.py` muda de tipo para o que a superfície sempre foi:

```python
NotFoundHandler = Callable[[Any], Awaitable[None]]  # (ctx)


class CommandOptions:
    on_error: ErrorHandler | None = None
    on_not_found: NotFoundHandler | None = None


class ResponderOptions:
    on_error: ErrorHandler | None = None
    on_not_found: NotFoundHandler | None = None
```

O dispatcher de comandos passa a chamar `await on_not_found(ctx)`.

### 2. O nome do comando não viaja no segundo argumento

`_nao_encontrado` já recebe `nome`, e o usa **só** no log. Para o
handler, o nome está em `ctx.interaction.data["name"]` — passar seria
duplicar informação que o contexto já carrega, e duplicar é a forma
clássica de os dois irem divergir.

## Consequências

- Quem já escreveu `async def h(ctx, erro)` para o `on_not_found` de
  **comando** quebra com `TypeError`. Ninguém deveria ter feito isso:
  a documentação nunca mostrou dois parâmetros — mas é uma quebra real
  e não silenciosa.
- O lado de responder não muda: já era um argumento.
- `ErrorHandler` continua sendo `(ctx, error)` para `on_error` nos três
  categorias. Só `on_not_found` sai dele.
- `test_on_not_found_de_comando_nao_vai_para_responder` passa a cobrir
  os dois ramos com a mesma assinatura de handler — que era o que ele
  queria cobrir desde o começo.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Dois argumentos dos dois lados, mudando o responder | Contraria as três fontes da ideia, e o segundo argumento é sempre `None` |
| Aceitar qualquer aridade com `inspect.signature` | Magia; o erro aparece no lugar errado e a assinatura deixa de ser contrato |
| Deixar como está (2 no comando, 1 no responder) | É o estado atual, e é exatamente o que o teste pegou: mesma opção, duas formas |
| Passar `nome` no segundo argumento | Duplica `ctx.interaction.data["name"]`, e duplicar é a forma clássica de divergir |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 01 Simplicidade | "Um argumento que sempre é `None` é um parâmetro sem leitor. Remover é mais honesto do que documentar." |
| 04 Modelos | A tabela acima é o argumento inteiro: cinco fontes independentes, quatro dizendo uma, e a minoritária é a única sem teste |
| 09 Testes | O lado de comando nunca foi coberto — a divergência sobreviveu porque só o lado com teste existia |
| 11 Idiomático | `on_error(ctx, error)` e `on_not_found(ctx)` são pareados pelo que cada um **tem** para dizer: um tem erro, o outro não |
| 17 Crítico | Contestou que a anotação de `config.py` fosse fraca — ela é o único lugar que o mypy conferiria. Resposta: é justamente por isso que ela tem que dizer a verdade |
| 18 Pragmático | A quebra é real mas pequena: o parâmetro nunca funcionou como documentado, então só quebra quem escreveu conforme a anotação e não testou |
| 19 Analista | Levantou que `ideias/exemplos/bot_configurado.py` é a amostra de uso mais próxima de produção — e ela tem um argumento |
| 20 Visionário | Propôs `on_not_found(ctx, motivo)` para distinguir "comando desconhecido" de "subcomando desconhecido". Não entrou: não há dois motivos no caminho atual, e é uma superfície nova para um caso que ainda não existe |

## Veredito do juiz: APROVADO

O juiz pediu que a quebra ficasse escrita em **Consequências** e não
só no parecer: é uma mudança de assinatura, e mudança de assinatura
que ninguém lê vira surpresa no próximo deploy.

## Divergência preservada

O Participante 17 (Crítico) defendeu manter dois argumentos alinhando
o responder ao comando, argumentando que a anotação de `config.py` é o
lado que o mypy confere. Não entrou porque a decisão não é "qual anotação
é mais conferível", é "qual assinatura o usuário escreve" — e nisso as
três fontes da ideia não discordam entre si.

## Confiança: 91%
