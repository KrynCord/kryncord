# 0019 — Descoberta de módulos e `bootstrap`

## Contexto

A ideia 01 §3 traz uma regra de ordem; a 04 §2 traz outra, e elas se
contradizem:

- **01 §3 r3**: "a ordem dos módulos carregados **não** é garantida"
- **04 §2**: "o bootstrap importa o pai antes dos filhos, garantindo que
  handlers ou definições globais sejam carregados antes dos dependentes"

E a 01 §B2 descreve um formato de glob que a 0009 (K5) já fechou como
pontilhado — mas deixa em aberto o `*_mod.py` e o valor de retorno.

## Decisão

### `bootstrap` garante pai antes de filho — a 04 §2 vence

O `bootstrap` resolve o padrão e **ordena por profundidade** antes de
importar. É uma garantia, não uma esperança, e custa um `sorted` por
profundidade.

A 01 §3 r3 estava descrevendo o que acontece quando você importa módulos
em qualquer ordem *à mão*. O bootstrap existe justamente para não ser
isso.

A recomendação "handlers não devem depender da ordem" permanece — mas é
recomendação de projeto, não regra do runtime. Garantia e recomendação
são coisas diferentes, e o documento não deve confundir as duas.

### Sintaxe do glob (K5, reafirmado)

| Padrão | Alcance |
|---|---|
| `mod` | módulo exato |
| `mod.*` | filhos diretos |
| `mod.**` | recursivo, **inclui subpacotes** |
| `*_mod.py` | arquivo |

O ponto é o separador — `mybot.commands.**`, nunca `/`.

### `*_mod.py` é mantido

Resolve B1. É a única forma de marcar explicitamente "este arquivo tem
side effects de registro" — e resolve um caso real: um pacote com
arquivos auxiliares (`utils.py`, `constants.py`) que não devem ser
importados pelo glob.

O custo é um sufixo. O benefício é que o glob pode ser agressivo sem
arrastar módulo errado.

### `bootstrap(*, modules, load_logs, before_load, client) -> Client`

```python
client = bootstrap(
    modules=["mybot.commands.**", "mybot.responders.*", "mybot.main"],
    load_logs=True,
)
```

**Retorno: `Client` apenas.** Sem relatório — teste assevera no `Client`
(`client.commands.instances()`), e um objeto de relatório seria outro
contrato para manter.

### Falha de import propaga com o padrão original

O traceback do módulo é preservado, e a mensagem adiciona qual padrão
estava sendo resolvido. Sem isso, um erro de import num `**` não diz
qual dos 40 módulos falhou.

### Import circular → erro claro

Quando `bootstrap` detecta import circular (importação parcial na pilha),
levanta mensagem sugerindo `bootstrap(modules=[...])` com a ordem
explícita. Não é auto-correção: é apontar a saída.

### `before_load(client)` roda **depois** dos imports

`Callable[[Client], Awaitable[None]] | Callable[[Client], None]`. A
função síncrona é adaptada com `await` condicional — mesmo critério dos
conversores (`0014`).

Ordem: imports → `before_load` → (o chamador chama `client.start()`).

`before_load` não pode registrar comandos (o registry já foi congelado
pelo import? não — o registry não congela). Na verdade ele **pode**: o
registry é reconstruído a cada `register`. `before_load` é para
conectar banco, carregar config externa, aquecer cache.

### `load_logs` imprime módulo e contagem

```
[mybot.commands.ping] 1 comando, 0 responder
[mybot.commands.__init__] 3 comandos, 1 responder
carregados 7 módulos, 12 comandos, 3 responders
```

Contagem por módulo é a informação que falta quando um comando "não
apareceu" — sem ela, é `print` manual.

## Consequências

- A 01 §3 r3 precisa ser corrigida no próprio `ideias/` (não é decisão
  nova, é contradição interna resolvida)
- `discovery/loader.py` importa `registry` e os três `create_*`
- A ordenação por profundidade é testável sem rede: dois pacotes, um
  filho que depende do pai

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Ordem não garantida (01 §3) | Deixa o bootstrap dependente de `pkgutil` — e o pai pode vir depois |
| Relatório de retorno | Outro contrato; `client.commands.instances()` já responde |
| Retirar `*_mod.py` | Perde a forma explícita de marcar side effects em pacote com utilitários |
| `before_load` antes dos imports | Precisa do `Client`, que nasce do bootstrap |
| Auto-corrigir import circular | Magia; o usuário precisa ver a pilha |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 19 Analista | A contradição 01 × 04 é factual e precisa de uma decisão, não de um "depende" |
| 06 Arquitetura | Garantia ordenada é uma propriedade que se testa; ordem aleatória não |
| 11 Idiomático | `sorted(key=depth)` é a implementação inteira |
| 09 Testes | `load_logs` com contagem por módulo é o que transforma "não apareceu" em diagnóstico |
| 18 Pragmático | `*_mod.py` custa um sufixo e resolve um caso real — não vale a discussão |
| 01 Simplicidade | Retorno `Client` só: um objeto, um teste |
| 17 Crítico | Perguntou se ordenação por profundidade é sempre suficiente; resposta: para import, sim — dependência Python não é grafo arbitrário |

**Veredito do juiz: APROVADO.**

**Divergência preservada:** o Participante 16 (Positivo) observou que
`load_logs` daria para estender com "tempo de import por módulo". Não
entrou na 1.0 — é métrica, não informação de carga, e Fase 5 tem
benchmarks.

**Confiança: 94%.**
