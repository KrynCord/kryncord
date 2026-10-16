# 0013 — Sintaxe de rota e roteador de `custom_id`

## Contexto

A ideia 08 descreve a sintaxe e o roteador; a 09 descreve `emit_responder`.
As duas se contradizem num ponto:

- 09 §7: "`emit_responder` não é o roteador. Faz lookup **exato** no
  registry. É a passagem do M4"
- 09 §3: exemplos de `emit_responder("/remember/2024-01-01")` com uma
  rota registrada como `/remember/:date` — isso **só** funciona pelo
  roteador

A também há ambiguidade sobre `?:param` contra `T | None`, sobre o que
faz com que `:` dentro do valor quebre, e as quatro regras de prioridade
da 08 §3 não cobrem empate.

## Decisão

### `emit_responder` usa o roteador, sem caminho alternativo

Um id literal registrado como rota sem parâmetros casa exatamente pelo
roteador — porque uma rota sem parâmetros **é** literal. Não há lookup
paralelo: dois caminhos de despacho são dois caminhos para testar.

A frase da 09 §7 era um resumo impreciso do que a 09 §3 já sabia ser
necessário.

### `?:param` e `T | None` são a mesma coisa; a anotação decide

```python
@responder("remember/:date?:")
async def _(ctx): ...  # opcional por ?


@responder("remember/:date")
async def _(ctx, date: str | None): ...  # opcional por anotação
```

Se as duas formas aparecerem e discordarem, `ResponderDefinitionError`
com a mensagem apontando o segmento. Anotação vence no caso de dúvida;
`?:` é a marca de opcionalidade para quem não quer escrever `| None`.

### `:` só tem significado na primeira posição do segmento do **padrão**

Um valor pode conter `:` — `2024-01-01T10:00:00` casa com `:date` sem
problema, porque a comparação é segmento a segmento, e `:` é lido só ao
analisar o padrão.

Isso remove a pergunta "e se o timestamp tiver `:`?" — não quebra.

### Segmentos literais casam exatamente, sem case-folding

`custom_id` é gerado por nós, não digitado por humano. Normalizar seria
trabalho que nenhum cliente vai precisar.

### Normalização antes do match

| Regra | Efeito |
|---|---|
| Trailing slash | `/foo/` == `/foo` |
| Segmento vazio | `/a//b` → `ResponderDefinitionError` |
| `**` no meio | erro, já na 08 §2 |
| `**` duplo | erro |

### `**` nomeado exige ≥1 segmento; `**` sem nome casa zero ou mais

Quando casa zero, `params["_"]` é a string vazia. Quem escreveu `**resto`
quer o resto — receber `""` é mais previsível do que não casar.

### Prioridade: peso por segmento, comparado da esquerda para a direita

Cada segmento do **padrão** recebe um peso:

| Segmento | Peso |
|---|---:|
| literal | 3 |
| `:p` | 2 |
| `?:p` | 1 |
| `**` | 0 |

Dois padrões que casam o mesmo id são ordenados pela sequência de pesos,
da esquerda para a direita, maior primeiro. `**` cai sempre por último
porque pesa 0.

Empate exato → `ResponderDefinitionError` na **importação**, citando os
dois módulos. Isso fecha a lacuna da 08 §3, que só descrevia quatro
regras e não dizia o que fazer quando elas empilhavam.

### `types` é filtro, não é prioridade

Dois registros com o mesmo padrão e `types` **diferentes** são dois
registros legítimos (ex: o mesmo botão em modal e em mensagem). Só há
conflito quando os tipos se **sobrepõem**.

`types` nunca entra na fórmula de peso — ele é aplicado antes, e um id
que não está nos tipos simplesmente não casa.

### O roteador é reconstruído a cada `register`

Sem congelamento. O custo é só tempo de import, acontece uma vez, e
não há risco de "registrei e o router não viu".

### Sem cache de matches na 1.0

O match é um dict-lookup mais comparação de segmentos. Um cache
adicionaria invalidação (todo `register` quebra) sem um gargalo medido.
Fica como benchmark da Fase 5.

## Consequências

- O `custom_id` documentado (`/remember/:date`) é gerado pelo K11 e
  parseado por este roteador — a cadeia fecha.
- `emit_responder` ganha um caminho só, o que é testável com um caso.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Lookup exato em `emit_responder` | Não acha `/remember/:date` com id `/remember/2024-01-01` — e o exemplo da própria ideia depende disso |
| `?:param` decide sobre `T \| None` | Dois sinais de opcionalidade brigando; anotação já existe e é a fonte do valor |
| Normalização case-insensitive | Trabalho para um id que ninguém digita |
| Cache de matches | Invalidação sem gargalo medido; piora a correção |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 19 Analista | A contradição 09 §7 × 09 §3 é factual: o exemplo da §3 não roda pela §7 — a decisão resolve com um caminho só |
| 06 Arquitetura | Um roteador, um registro, uma tabela de prioridade — nada paralelo |
| 22 Contexto | `custom_id` é gerado, não digitado: case-insensitive seria normalização de dado sintético |
| 09 Testes | Empate na importação é o único momento em que você **consegue** reclamar, porque depois os dois módulos já foram carregados |
| 17 Crítico | Perguntou sobre cache: respondeu que o gargalo não foi medido, e a Fase 5 mede |
| 11 Idiomático | Peso por segmento é uma tupla de int comparável — sem funções de ranking nem functools |
| 04 RAM | Sem cache é uma tabela a menos para manter consistente |

**Veredito do juiz: APROVADO.**

**Divergência preservada:** o Participante 02 (Performance) queria o cache
desde já, argumentando que um bot com 500 respondeiros repetiria a
comparação de segmentos. Não prevaleceu porque o custo por chamada é
~µs e a invalidação é o custo real. Fica registrado para a Fase 5.

**Confiança: 91%.**
