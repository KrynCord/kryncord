# 0016 — Máquina de estados de interação

## Contexto

A ideia 14 descreve estados e transições, mas deixa em aberto: quem
guarda o estado, qual a classe de erro, o que acontece ao responder duas
vezes, e o comportamento de `ephemeral`.

Há também três nomes conflitantes para o mesmo problema:
`InteractionTimeout` (14 §12), `InteractionTimeoutError` (0009) e
`RateLimited` (11 §4) contra `RateLimitError` que já existe em
`errors.py`.

## Decisão

### Quatro estados

```
UNANSWERED ──reply──────────────> ANSWERED
     │                              ▲
     ├──defer_reply/update──> DEFERRED ──edit_reply/update──┘
     │                              │
     └──send_modal──────────> MODAL   (terminal)
```

| Estado | Significado |
|---|---|
| `UNANSWERED` | nada enviado |
| `DEFERRED` | defer enviado (reply ou update) |
| `ANSWERED` | resposta final enviada |
| `MODAL` | modal aberto — **terminal** |

### O dono é `InteractionContext`, não o modelo

`Interaction` continua dado puro (`0003`). O estado mora em
`interactions/response.py`, num objeto por dispatch.

Isso mantém a regra da biblioteca inteira: **modelos são imutáveis,
estado vive no cliente.**

### Transições permitidas

| De | Ação | Para |
|---|---|---|
| `UNANSWERED` | `reply` | `ANSWERED` |
| `UNANSWERED` | `defer_reply` / `defer_update` | `DEFERRED` |
| `UNANSWERED` | `send_modal` | `MODAL` |
| `DEFERRED` | `edit_reply` / `update` | `ANSWERED` |
| `DEFERRED` | `send_modal` | `MODAL` |
| `ANSWERED` | `edit_reply` / `update` | `ANSWERED` (edição é idempotente) |
| `ANSWERED` | `reply` / `defer` / `send_modal` | **erro** |

`send_modal` a partir de `UNANSWERED` é permitido: o Discord aceita modal
como resposta inicial de interação de comando e de componente. A restrição
da 14 §3 era "não abra modal depois de já ter respondido" — que é a
linha `ANSWERED → send_modal`.

### Classe de erro: `InteractionStateError`

Não `DispatchError`. Falha de transição não é falha de despacho: é o
código chamando na ordem errada, e a hierarquia correta é
`KrynCordError` → `InteractionStateError`.

`BlockHandlers` é a exceção **controlada** (0009 K7) — capturada pelo
dispatcher. `InteractionStateError` é um **erro de uso**, que escapa.

### `is_responded()` é True em `DEFERRED`, `ANSWERED` e `MODAL`

Um defer já respondeu — é por isso que o nome é `responded` e não
`replied`. Quem pergunta "posso responder?" quer `False` só em
`UNANSWERED`.

### `ack()` é idempotente

- `UNANSWERED` → `DEFERRED_UPDATE_MESSAGE` implícito
- `DEFERRED` / `ANSWERED` → no-op silencioso
- `MODAL` → `InteractionStateError`

No-op em vez de erro porque `ack()` existe exatamente para "garantir que
foi acknowledge", e reclamar que já foi é reclamar que o chamador atingiu
o objetivo.

### Ephemeral é flag, e é idempotente

`MessageFlags.EPHEMERAL` na resposta inicial. Repetir com a mesma flag é
ok; flag **contraditória** (responder ephemeral e depois não) →
`ValueError`.

`edit_reply` e `delete_reply` em mensagem ephemeral funcionam — o
Discord permite, e a biblioteca não deve restringir o que a API aceita.

### Expiração do token: `InteractionTimeoutError`

15 minutos após a interação. Levantado ao responder; é o que o
`on_error` default pega para **não** tentar responder de novo (que
falharia com 400).

O nome escolhido é o do `0009` — `InteractionTimeout` (sem sufixo)
fica abandonado, porque tudo que herda de `KrynCordError` na
biblioteca leva `Error`.

### `RateLimited` vira `RateLimitError`

Já existe em `errors.py`. A 11 §4 usava o nome curto; adicionar um
segundo seria uma exceção duplicada para o mesmo evento.

### Um `InteractionContext` por dispatch, compartilhado

Comandos e responders usam a mesma máquina — não há duas, porque uma
interação é uma interação, seja `/comando` ou um botão.

## Consequências

- `interactions/response.py` ganha a máquina e a transição é o único
  ponto que pode mandar a API — centraliza o teste de ordem.
- `is_responded` pode ser consultado por middleware para decidir se
  vale a pena `defer`.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Estado no modelo `Interaction` | Quebra `frozen=True`; e o mesmo `Interaction` pode ser entregue a dois contextos |
| `InteractionTimeout` sem sufixo | Tudo que herda de `KrynCordError` leva `Error` |
| `ack()` erro se já respondido | `ack()` é idempotente por definição; o no-op é o comportamento útil |
| Modal só a partir de `DEFERRED` | Discord aceita como resposta inicial; restringir seria bug |
| Máquina separada para responders | Uma interação é uma interação; duas máquinas, dois conjuntos de bugs |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 19 Analista | Listou `InteractionTimeout`, `InteractionTimeoutError` e `RateLimited` como três nomes para dois eventos — a decisão reduz para dois |
| 06 Arquitetura | Estado no dono (contexto), não no dado (modelo) — a mesma régua do `0008` |
| 08 Segurança | `ANSWERED → reply` como erro barato é o que impede resposta dupla em produção |
| 22 Contexto | Modal como resposta inicial é comportamento documentado do Discord; restringir é inventar regra |
| 09 Testes | Quatro estados × quatro ações = 16 casos, todos determinísticos e sem rede |
| 18 Pragmático | `ack()` idempotente evita condicional em todo call site do usuário |

**Veredito do juiz: APROVADO.**

**Divergência preservada:** o Participante 04 (RAM) propôs guardar o
estado como `IntEnum` em vez de string. Não prevaleceu: as strings são
comparáveis em teste e em log sem `int(...)`; o ganho de RAM de quatro
enums seria medido em bytes por dispatch.

**Confiança: 93%.**

---

## Correção registrada na implementação

A seção "Ephemeral é flag, e é idempotente" estava **errada**, e o erro
só apareceu ao escrever o teste.

Ela dizia: "repetir com a mesma flag é ok; flag contraditória →
`ValueError`". Para isso ser alcançável seria preciso duas respostas
iniciais — e a segunda já é `InteractionStateError` **antes** de
qualquer comparação de flag. A máquina de estados cobre o caso, e um
segundo guarda seria código que nunca roda.

Pior que inútil: daria a impressão de uma proteção que não existe. Alguém
lendo o registro acharia que trocar a flag dá `ValueError`, quando na
prática dá `InteractionStateError` com outra mensagem.

O guarda foi removido, e o teste `test_segunda_resposta_ephemeral_e_erro_de_estado`
é a prova documental de que a máquina cobre — é uma correção da
decisão, não uma simplificação arbitrária.

**Regra que sobra:** `ephemeral` é escolha única por interação, e quem
garante é a máquina, não um campo guardado.

**Confiança revisada: 88%** — a decisão da máquina continua correta; o
que caiu foi uma das especificações periféricas, e isso é o tipo de
coisa que só se verifica implementando.

**Próxima verificação:** o `InteractionTimeoutError` (expiração em 15
minutos) ainda não tem implementação — quando tiver, precisa do mesmo
teste de alcançabilidade.
