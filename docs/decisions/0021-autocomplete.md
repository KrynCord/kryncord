# 0021 — Autocomplete

## Contexto

A ideia 06 descreve autocomplete de duas formas — função na opção (A) e
função no comando (B) — e deixa em aberto a prioridade, o fallback, o
que fazer quando as duas existem, e como o `AutocompleteContext` se
relaciona com o `CommandContext`.

## Decisão

### Duas formas coexistem; **B tem prioridade**

| Forma | Como | Escopo |
|---|---|---|
| A | `create_command(option=Option(autocomplete=fn))` | uma opção |
| B | `@meu_comando.autocomplete("nome_opcao")` | uma opção |
| genérica | `@meu_comando.autocomplete()` sem nome | todas as opções do comando |

B vence A porque é o caminho declarativo depois da definição, e porque
permite registrar depois do `create_command` — o que é necessário quando
o conversor depende de algo que só existe depois.

**Ambas na mesma opção → `CommandDefinitionError`**, com o nome da opção
e os dois módulos. Não é "B vence em silêncio": dois autores brigando
pela mesma opção é erro, não preferência.

### `AutocompleteContext`

```python
@dataclass(frozen=True, slots=True)
class AutocompleteContext:
    focused: str          # nome da opção em foco
    focused_value: Any    # o que o usuário digitou até agora
    options: ...          # accessor tipado, igual ao do CommandContext
    interaction: Interaction
    client: Client
    guild: Guild | None
    channel: Channel | None
    user: User
    ...
    async def respond(self, choices) -> None
    def is_responded(self) -> bool
```

`focused` e `focused_value` são **atributos**, não métodos — o valor é
dado, não computação.

### `ctx.options.focused()` (06 §7) é abandonado

Fica um só lugar para o foco: o `AutocompleteContext`. O accessor de
opções não ganha um método especial que só existe dentro de autocomplete.

### Ordem de resolução

```
B (função na opção)   -> A (função na Option)  -> genérica do comando  -> resposta vazia
```

Resposta vazia é o fallback legítimo: o Discord mostra "nenhum resultado"
e não reclama. Uma exceção aqui fecharia a janela de autocomplete com
erro.

### Truncamento silencioso, com log em DEBUG

| Limite | Comportamento |
|---|---|
| 25 escolhas | corta as 25 primeiras e loga em DEBUG |
| 100 caracteres por escolha | corta o valor e loga em DEBUG |

**Não** avisa o usuário: o autocomplete é sugestão, e avisar polui a
janela. DEBUG porque é o nível que existe quando você quer ver isso.

### O registro fica no `CommandInstance`

```python
CommandInstance.autocomplete: dict[str, Callable]  # por nome da opção
CommandInstance.autocomplete["*"]  # genérica
```

Nenhuma estrutura paralela no registry — o autocomplete pertence ao
comando, como já foi decidido no `0011`.

### O tipo de resposta é `APPLICATION_COMMAND_AUTOCOMPLETE_RESPONSE`

O `respond()` manda `type=8`, não `type=4`. É o tipo próprio do
autocomplete, e confundi-lo com `CHANNEL_MESSAGE_WITH_SOURCE` é o erro
que mais aparece em biblioteca de terceiros.

## Consequências

- `commands/autocomplete.py` recebe `AutocompleteContext` e o resolver
- O `interaction_create` do `0020` precisa distinguir `type=8` e
  despachar para o autocomplete, não para o comando
- O accessor de opções do `CommandContext` é reaproveitado

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Só a forma A | Não permite registrar depois do `create_command` |
| Só a forma B | O `Option(autocomplete=...)` já está no payload e seria ignorado |
| B vence A em silêncio | Dois autores brigando por uma opção, e o perdedor não sabe |
| Erro quando não há conversão | Fecha a janela com exceção; vazio é o resultado legítimo |
| `ctx.options.focused()` junto | Dois lugares para a mesma pergunta |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 06 Arquitetura | Duas formas precisam de precedência explícita e de erro em empate — nunca de preferência silenciosa |
| 22 Contexto | O Discord trata autocomplete como sugestão: silêncio é o formato |
| 09 Testes | As quatro etapas do fallback são distinguíveis e testáveis sem rede |
| 01 Simplicidade | `focused` como atributo, não método — é dado |
| 17 Crítico | Perguntou sobre os 25: resposta — cortar é o único comportamento que não fecha a janela |
| 11 Idiomático | `dict[str, Callable]` + `"*"` é mais simples que uma hierarquia de regras |

**Veredito do juiz: APROVADO.**

**Divergência preservada:** o Participante 20 (Visionário) queria
suporte a autocomplete com **mais de um** campo focável (o Discord
permite só um por vez). Não entrou — a API do Discord atual só entrega
um, e preparar para o hipotético seria superfície morta.

**Confiança: 92%.**
