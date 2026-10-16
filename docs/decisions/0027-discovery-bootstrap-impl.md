# 0027 — `bootstrap`: ordem de import, glob e o que ele não faz

## Contexto

O `0019` fechou o contrato do `bootstrap`: ordena por profundidade,
mantém `*_mod.py`, devolve `Client` só, propaga falha de import com o
padrão original, `before_load` depois dos imports, `load_logs` com
contagem por módulo.

Codar levantou quatro perguntas que o próprio `0019` deixou em aberto —
uma delas é uma contradição interna no próprio documento.

### A contradição interna

O `0019` mostra:

```python
client = bootstrap(modules=[...], load_logs=True)
```

sem `await`. Mas a mesma decisão escreve que `before_load` aceita
`Callable[[Client], Awaitable[None]]` e que "a função síncrona é
adaptada com `await` condicional". Um `bootstrap` síncrono **não tem
onde** esperar uma função assíncrona.

A ideia 01 §2 já trazia `client = await bootstrap(...)`. O snippet do
`0019` perdeu o `await` ao ser reescrito.

### As outras três

1. O `0019` diz "`*_mod.py` | arquivo", mas o glob é sobre **caminho de
   importação** (`K5`: ponto, não barra). O que significa um padrão com
   `.py` no fim?
2. `pkgutil.walk_packages` executa os `__init__.py` durante a varredura
   — o loader importaria módulos que o padrão nem casa.
3. Um padrão que não casa nada: erro, aviso ou silêncio?

## Decisão

### 1. `bootstrap` é `async`

```python
client = await bootstrap(
    modules=["mybot.commands.**", "mybot.events"],
    load_logs=True,
    before_load=before_load,
)
```

A assinatura da ideia 01 §2 era essa; o snippet do `0019` estava errado,
e esta decisão é o registro da correção (mesma classe da correção do
`ready` no `0025`).

A alternativa — `bootstrap` síncrono com `before_load` só síncrono —
cortaria o caso de uso que existe justamente para o hook: preparar
banco, aquecer cache, carregar config externa, tudo `await`.

Ordem inalterada: **imports → `before_load` → devolve → o chamador chama
`client.start()`**. O `bootstrap` não liga o bot (`K4`: sem sync
automático, e sync é outro assunto).

### 2. Resolução sem efeito colateral; import, depois

Dois passos separados, e a separação é o ponto:

| Passo | Função | Efeito |
|---|---|---|
| Resolver | `resolve(pattern) -> tuple[str, ...]` | **nenhum** — `importlib.util.find_spec` + `pkgutil.iter_modules` |
| Carregar | `importa(nome)` | executa o módulo |

`find_spec` localiza sem executar; `iter_modules` lista sem importar.
Ou seja: a varredura **não** roda `__init__.py` dos pacotes que não
importam, e o loader importa exatamente o que o padrão casou.

Isso resolve o item 2 e torna `resolve` testável sem importar nada — que
é o que a ideia 01 §8 pede para `test_loader.py`.

### 3. Sintaxe do glob, fechada

| Padrão | Significado |
|---|---|
| `mybot.commands` | o módulo exato |
| `mybot.commands.*` | filhos diretos — **não** inclui o pacote |
| `mybot.commands.**` | o pacote **e** tudo abaixo |
| `mybot.tools.*_mod.py` | remove `.py`; `*` é um segmento; `_mod` é sufixo literal |
| `mybot.cogs` | o pacote — o `__init__.py` roda, nada além dele |

O ponto é o separador (`K5`), nunca `/`.

Três convenções em uma linha:

- `.py` no fim marca padrão de arquivo: **o sufixo sai antes de parser**,
  e o que sobra é um padrão de módulo com curinga de um segmento. Nada
  de filesystem, nada de caminho — o `K5` proíbe a barra justamente
  porque `bot testes/` tem espaço e não vira pacote nunca.
- `**` inclui o próprio pacote porque é o `__init__.py` que tem os
  `import` laterais do pacote — e o `load_logs` do `0019` conta
  `[mybot.commands.__init__] 3 comandos`, que só existe se ele entrar.
- `*` não inclui o pacote: ele é "os filhos", e incluir o pai duplicaria
  tudo no `**`.

Sobreposição (`mybot.commands` e `mybot.commands.**` no mesmo `modules`)
não é erro: `sys.modules` já cacheia, e o loader registra o que for novo
(`01` §3 r1).

### 4. Ordem por profundidade, com desempate alfabético

```python
sorted(nomes, key=lambda n: (n.count("."), n))
```

Pai antes de filho é a garantia que o `0019` escolheu (a `04` §2 venceu
a `01` §3 r3). O desempate alfabético é o que faz o `load_logs` ser
estável entre execuções — sem ele, dois irmãos trocariam de lugar e o
log pareceria mudar sem motivo.

### 5. Falha de import propaga com o padrão e a causa

```python
raise ImportError(f"falha ao importar {nome!r}, resolvido do padrão {padrao!r}: {exc}") from exc
```

`from exc` mantém o traceback original na cadeia (`The above exception
was the direct cause`), que é o que o `0019` pediu. Sem o padrão, um
erro num `**` de 40 módulos não diz qual falhou; sem a causa, o padrão
não diz o que houve. Os dois juntos.

### 6. Import circular é apontado, não corrigido

Detecção pela mensagem que o próprio Python dá —
`cannot import name ... from partially initialized module` — mais o
`ModuleNotFoundError` cujo nome parcial está em `sys.modules`.

A mensagem sugere a saída, na forma que o `0019` escreveu:

> `mybot.commands.foo` está em importação circular. Use
> `bootstrap(modules=["mybot.core", "mybot.commands.**"])` com a ordem
> explícita.

Não é auto-correção: é apontar. A pilha fica visível porque a exceção é
levantada de dentro do `except`.

### 7. `load_logs` conta por módulo, ao final

Depois de todos os imports, agrupa por `handler.__module__`:

```
[mybot.commands.ping] 1 comando, 0 responder
[mybot.commands.__init__] 3 comandos, 1 responder
[mybot.events.geral] 0 comando, 0 responder
carregados 7 módulos, 12 comandos, 3 responders
```

Agrupar **depois** em vez de contar antes/depois de cada import é o que
sobrevive a um módulo que registra com handler definido em outro (re-export
comum em `__init__.py`). Contagem por delta contaria errado nesse caso.

Módulo que registrou zero continua aparecendo: "não apareceu" é a
informação que o `0019` quis dar, e ela é visível só quando a linha
existe com zero.

Sai por `log.info` do logger `kryncord.discovery`, não por `print` —
`load_logs=False` vira `DISABLED` nesse logger, e quem já tem handler
configurado continua ouvindo.

### 8. Padrão que não casa nada: `DEBUG`, não erro

- **Pacote base não existe** → `ModuleNotFoundError`: é erro de digitação
  e o loader sabe o nome.
- **Pacote existe, nenhum filho casa** → `log.debug`. É o caso legítimo
  do `*_mod.py` (`B1`): o glob existe para poder ser agressivo sem
  arrastar módulo errado, e falhar porque ainda não há nenhum arquivo
  `_mod` obrigaria a criar arquivo vazio.

O `B4` da ideia 01 ("aviso de padrão amplo demais") não entra: é um lint,
não uma informação de carga, e o `load_logs` já dá a contagem que torna
o padrão amplo visível.

### 9. O que ele **não** faz — mantido

| Não faz | Por quê |
|---|---|
| `client.start()` | o ciclo de vida é do chamador (`01` §6) |
| `sync()` de comandos | `K4` — sync explícito, e são 2/hora |
| Relatório de retorno | `0019` — `client.commands.instances()` já responde |
| Auto-corrigir circular | magia; o usuário precisa ver a pilha |

## Consequências

- `discovery/` ganha `loader.py` (resolve + importa) e `bootstrap.py` (o
  `async def` público). `imports.py` e `validation.py` da ideia 01 não
  existem: `resolve` é o `imports`, e validação não há — nada de
  definição nasce no loader.
- `bootstrap` exportado da raiz (`from kryncord import bootstrap`).
- `resolve()` é puro e coberto sem importar, como a ideia 01 §8 pede.
- `Client.commands` / `Client.responders` (do `0026`) são o que o
  `load_logs` conta.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `bootstrap` síncrono | Não há onde esperar um `before_load` assíncrono — e é o caso de uso do hook |
| `pkgutil.walk_packages` na varredura | Executa `__init__.py` dos pacotes percorridos, importando módulos que o padrão não casou |
| `.py` virava caminho de disco | `K5` proíbe a barra; `bot testes/` é o contraexemplo que não vira pacote |
| `**` não inclui o pacote | O `__init__.py` com os imports laterais sairia do `load_logs`, e o `0019` mostrou a linha dele |
| Erro quando o padrão não casa nada | Obriga criar `_mod.py` vazio — o `B1` existe para o glob poder ser agressivo |
| Contar antes/depois de cada import | Erra em re-export (`__init__.py` registrando handler definido em outro módulo) |
| `print` no `load_logs` | `load_logs=False` não silenciaria quem já tem handler |
| Auto-corrigir import circular | "Não é auto-correção: é apontar" — o `0019` já tinha escrito |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 19 Analista | A contradição `async` × snippet sem `await` estava no próprio `0019` — dois documentos contradizendo, um deles o contrato |
| 06 Arquitetura | Separar resolver de importar é o que torna o loader testável sem efeito colateral |
| 09 Testes | `resolve()` puro é exatamente o `test_loader.py` da ideia 01 §8, sem `sys.path` |
| 11 Idiomático | `.py` como marcador de sintaxe, não de caminho — mantém o glob sobre importação como o `K5` quer |
| 18 Pragmático | Agrupar depois sobrevive a re-export; contar delta não |
| 17 Crítico | Perguntou se `**` incluindo o pacote duplicaria o que `*` já traz; resposta: os dois curingas têm semântica diferente e a sobreposição é silenciosa por `sys.modules` |
| 01 Simplicidade | Dois passos, um puro e um com efeito — a estrutura inteira do módulo caiu nessa linha |
| 08 Segurança | `from exc` na falha de import é o que mantém o traceback original, que é o pedido escrito do `0019` |

**Veredito do juiz: APROVADO.** O Juiz registrou que a correção do
snippet (`await`) precisa aparecer no corpo da decisão, não só na
alternativa — incorporado na §1.

**Divergência preservada:** o Participante 16 (Positivo) reabriu o `B4`
(propor aviso de padrão amplo demais), lembrando que o `0019` não o
registrou como rejeitado. Não entrou: o `load_logs` já imprime a
contagem, e aviso sobre escolha de configuração é ruído.

**Confiança: 91%.**
