# 0018 — Sincronização de comandos

## Contexto

A ideia 04 §7 diz que `sync()` usa os métodos `api/applications.py`, mas
esses métodos ainda não existem para o escopo — `K1` anotou a lacuna: não
há caminho REST para `PUT /applications/:id/guilds/:id/commands`.

Também não estão decididos: `PUT` contra `PATCH`, o vocabulário do diff,
o `verbose`, e o comportamento quando o rate limit global (2/h) bate.

## Decisão

### `PUT` bulk por escopo, não `PATCH` por id

| Método | Quando |
|---|---|
| `PUT /applications/:app/commands` | escopo global, uma chamada |
| `PUT /applications/:app/guilds/:gid/commands` | cada guild, uma chamada |

`PATCH` só é útil para alterar **um** comando. Como `sync()` conhece o
conjunto inteiro, o bulk é idempotente e custa uma chamada — enquanto
`PATCH` custaria uma por comando.

O rate limit real do Discord aqui é o **global: 2 requisições por
hora**. Com `PATCH` e 50 comandos, um sync completo levaria 25 minutos.

### Diff **antes** de enviar

`sync()` primeiro busca o estado remoto (`GET`), compara, e só envia se
algo mudou.

Vocabulário de ação — uma palavra por linha:

| Ação | Quando |
|---|---|
| `CREATED` | existe local, não remoto |
| `UPDATED` | existe nos dois, payloads diferentes |
| `DELETED` | existe remoto, não local |
| `UNCHANGED` | payloads iguais |

Comparação por **igualdade profunda do payload serializado** (`dict ==
dict`). Sem hash: é mais simples, correto, e o volume (dezenas de
comandos) não justifica otimização.

### `sync()` devolve `SyncReport`

```python
@dataclass(frozen=True, slots=True)
class SyncReport:
    created: tuple[str, ...]
    updated: tuple[str, ...]
    deleted: tuple[str, ...]
    unchanged: tuple[str, ...]
    scopes: tuple[int | None, ...]
```

Sem relatório, o teste teria que espionar o transporte — e o relatório
é barato.

### `sync(apply=False)` é o dry-run

Devolve o `SyncReport` sem mandar nada. É a única forma de verificar "o
que mudaria" sem tocar no Discord, e custa uma linha.

### Rate limit: espera, não falha

`sync()` usa o `BucketManager` que já existe. O global (2/h) e o de
guild (5/5s) têm buckets separados.

Bloquear `sync()` por até 30 minutos é inaceitável. DECISÃO: o `sync`
espera o bucket **se** houver tempo estimado abaixo de um limite, e
falha com `RateLimitError` informando quando acima — porque um `sync`
travado por meio hora não tem como ser cancelado de forma útil.

Hmm — simplificando: `sync()` espera o bucket normalmente (é uma
operação de startup, não de hot path). `apply=False` nunca espera, porque
não envia.

### Validação antes da primeira requisição

Todas as definições são validadas **antes** de montar qualquer payload.
Um grupo sem subcommand derruba o sync inteiro, com o nome do grupo —
não depois de já ter enviado as metade.

Isso inclui: opções inválidas, descrição ausente em CHAT_INPUT,
context menu com options.

### `verbose` e `load_logs` são independentes

| Flag | Dono | O quê |
|---|---|---|
| `verbose` | `CommandOptions` | imprime as linhas do `SyncReport` |
| `load_logs` | `bootstrap()` | imprime cada módulo carregado e a contagem de handlers |

Os dois podem estar ligados, desligados, ou qualquer combinação — são
perguntas diferentes.

### A lacuna REST que precisa ser preenchida

`api/applications.py` ganha quatro métodos:

```python
async def commands_global(app_id) -> list[ApplicationCommand]
async def bulk_overwrite_global(app_id, definitions) -> None
async def commands_guild(app_id, guild_id) -> list[ApplicationCommand]
async def bulk_overwrite_guild(app_id, guild_id, definitions) -> None
```

`RESTClient` não precisa de nada novo — `PUT` já existe (`BODYLESS_METHODS`
é `GET`/`DELETE`; `PUT` com corpo está no caminho normal). É só a
`api/` que falta.

## Consequências

- Fase 4 começa pela lacuna REST, antes do `sync.py`
- `SyncReport` é o contrato de teste do `sync` — sem rede
- Um sync com zero mudanças faz **uma** chamada `GET` por escopo

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `PATCH` por comando | 50 comandos × rate limit global 2/h = 25 minutos |
| Sync sem diff (sempre PUT) | PUT mesmo assim é uma chamada, mas o relatório fica `CREATED`-falso e `verbose` mente |
| Comparar por hash | Precisa de hash estável de dict; igualdade profunda já resolve |
| Falhar no rate limit | `sync` é startup — esperar é o comportamento certo |
| Vocabulário `aparar`/`remover` (11 §4) | `CREATED`/`UPDATED`/`DELETED` é o vocabulário de diff que todo mundo já lê |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 02 Performance | O gargalo não é CPU, é o rate limit global 2/h — `PATCH` o transforma em fila de meia hora |
| 22 Contexto | Bulk overwrite é a operação nativa do Discord para "meu conjunto é este"; `PATCH` é para edição pontual |
| 19 Analista | Sem `SyncReport`, o teste precisaria espionar o transporte — o relatório já é o instrumento |
| 18 Pragmático | A lacuna REST (`0009` K1) tem que vir antes do `sync.py`, ou o `sync` não tem como ser escrito |
| 09 Testes | `apply=False` dá dry-run sem rede, e o relatório é o mesmo objeto |
| 07 Concorrência | Esperar o bucket em startup é seguro; em hot path não seria |
| 17 Crítico | Perguntou sobre `DELETE` implícito do bulk — resposta: sim, apaga os que saíram do registro, e isso é o comportamento desejado de um sync |

**Veredito do juiz: APROVADO COM AJUSTES.** O ajuste: validação completa
antes da primeira requisição, para não mandar metade antes de descobrir
o erro. Incorporado.

**Divergência preservada:** o Participante 01 (Simplicidade) queria
`sync()` sem `apply` — "se não mudou, não envia" já cobre. Não prevaleceu
porque o dry-run é a única forma de auditar sem rede.

**Confiança: 91%.**
