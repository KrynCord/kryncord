# 0009 — Superfície de comandos, eventos e responders: K1–K12

## Contexto

`ideias/12-encaixe-no-projeto.md` §7 abriu 12 decisões para serem
fechadas **antes** de codar a Fase 4, porque todas desenham a API
pública — e a superfície pública é a parte cara de mudar depois.

Duas já tinham mudado de figura entre a escrita das ideias e a
construção da Fase 3:

- **K2** propunha `class CachePolicy(StrEnum)` com `ANY`/`CACHED`/`FRESH`.
  O nome `CachePolicy` passou a ser o dataclass de política de
  armazenamento (`0008`), então não dá para reusar.
- **K6** proponha `dispatch_mode` com default `concurrent`, e o
  `events/dispatcher.py` já é sequencial por decisão do `0006`, com a
  razão documentada.

E **K1** encontrou um obstáculo que nenhuma das opções previa: `global`
é palavra reservada do Python, e `@command(global=True)` é
`SyntaxError`.

## Decisão

### K1 — Escopo do registro: `is_global` / `guild`

Três parâmetros mutuamente exclusivos, e não um booleano só:

```python
@command(is_global=True)        # global — propaga em até 1 hora
@command(guild=123)             # uma guild — propaga na hora
@command(guild=(123, 456))      # várias guilds
```

`guild` aceita `int | Sequence[int]`. Um boolo cobriria o primeiro caso
e não os outros dois, e registrar numa guild específica não é curiosidade:
é como se testa comando sem esperar a propagação global, e como se
rola para um servidor antes de todos.

Passar `is_global` junto com `guild` é `ValueError` na **importação**,
não uma escolha silenciosa — dois sinais contradizendo sobre o mesmo
comando é erro de definição, e o `DefinitionError` existe para isso.

`bool` é rejeitado antes de `int`, como já faz `_resolve.py`: um JSON
com `guild: true` é JSON quebrado, não a guild 1.

**Nenhum dos dois** significa o default de `CommandOptions`, que é
`is_global=True` — o comportamento do Discord por omissão e o que
quase todo bot quer. Se mudar, muda na opção, não no decorator.

### K2 — `cache=` dos responders: `Literal`

```python
@responder("/fruits", types=[ResponderType.STRING_SELECT], cache="cached")
```

`Literal["any", "cached", "fresh"]`, default `"any"`.

Mantém a sintaxe já escrita nas ideias inteiras, o mypy rejeita erro de
digitação, e o `fresh` continua disponível sem mais um tipo no
`__init__.py`. Um `StrEnum` seria mais explícito, mas verboso para o
argumento mais repetido dos responders.

O que ele **não** é, e isso precisa estar documentado no próprio
argumento: não tem relação com `Config.cache`. `cache="cached"` diz
"dispara só se a mensagem de origem estiver no cache" — e com
`CachePolicy` no default, `messages=0`, **nada** é cacheado, então
`cached` nunca dispara. É armadilha prevista e assumida: quem escolhe
`cached` escolhe também ligar `messages`.

### K3 — Conversores: anotação + `parse=`

Anotação é o default e cobre a maioria; `parse=` explícito cobre o
resto.

```python
async def remember(interaction, date: datetime): ...  # anotação
async def remember(interaction, date=parse_datetime): ...  # explícito
```

Dois caminhos, um óbvio. Só anotação seria parede para tipo sem
`from_payload` nem conversor registrado; só `parse=` obriga todo handler
a ser mais verboso para fazer o mesmo.

### K4 — `bootstrap` **não** dispara sync

Sync de comandos globais é limitado a **2/hora** pelo Discord. Disparar
numa importação quebraria teste, hot-reload e qualquer script que só
quer carregar módulos — e um import com efeito de rede é o tipo de
comportamento que ninguém descobre lendo o código.

`sync()` continua explícito.

### K5 — Glob usa ponto

```python
bootstrap("mybot.commands.**")
```

É import de Python, não filesystem. Barra mente sobre o que está sendo
resolvido e leva a gente a caminho de disco — cujo contraexemplo é a
pasta deste projeto, `bot testes/`, que tem espaço e não vira pacote
nunca. Regex daria muito mais poder e muito mais erro para um caso
comum que o glob cobre.

### K6 — `dispatch_mode`, mas o default **não** muda

`EventOptions(dispatch_mode="sequential" | "concurrent")`, default
`"sequential"`.

A ideia 10 recomendava `concurrent`. O `0006` já decidiu sequencial
com razão documentada (exceção isolada, cancelamento propaga,
paralelismo = `Client.spawn` dentro do handler), e o dispatcher já roda
com 941 testes verdes em cima disso. Inverter o default agora custaria
a semântica de trabalho já construída; inverter **depois** custaria
quem já escreveu em cima.

`concurrent` vira opt-in, e o `Client.spawn` continua sendo o
paralelismo semântico.

### K7 — `block()` é exceção

```python
async def manha(event):
    block("morning")
```

`BlockHandlers(tags)` capturado pelo dispatcher. Uma exceção se levanta
de qualquer lugar da pilha — dentro de `if` profundo, depois de um
`await`, no meio de um `try` — sem precisar de `return` em cada caminho
de saída. Com flag, esquecer um `return block()` derruba o resto dos
handlers em silêncio.

### K8 — `client.run()` existe

```python
client.run(token)
```

É o ponto de entrada que todo mundo espera vindo de discord.py. Sem
ele, todo hello-world ganha uma camada de `asyncio.run` na frente, e o
exemplo do README passa a ser mais longo que o código do bot.

Chamado dentro de um loop já rodando, eleva erro claro em vez de
rodar e estourar depois — o caso existe (notebook, outro framework),
e a mensagem de erro sai mais barata que o traceback.

### K9 — Handler com `*args` é aceito

```python
async def proxy(*args): ...
```

`*args`/`**kwargs` é o pedido explícito de "me dá tudo": middleware de
log, proxy, teste genérico. A validação de aridade é pulada, que é
exatamente o que quem escreveu `*args` quis dizer.

### K10 — `emit_responder` retorna `False`

Quem emite à mão recebe `bool` e decide. Não chama `on_not_found`.

Chamada programática não é "isso não foi configurado ainda" — mostrar
o aviso do usuário final porque o id veio de código nosso é expor erro
não é erro. Um botão que ninguém atendeu e um id escrito errado são
dois casos diferentes, e o chamador é quem sabe qual viveu.

### K11 — `build_custom_id` fica em `responders/ids.py`

```python
from kryncord import build_custom_id
```

Parser e construtor da sintaxe de rota no mesmo lugar: um só arquivo
define o formato, e não tem como os dois divergirem. Viver em
`components/` separaria o construtor do router, e viver na raiz do
pacote deixaria sem dono.

Exportado na raiz porque é o helper que o usuário chama por último, na
linha do código dele.

### K12 — `kryncord.registry` global existe

`@command` num módulo tem que registrar em algum lugar sem que o
usuário aponte um client — é o que a arquitetura quer ao proibir Cogs.

O global existe e é o default. `Client(registry=...)` é o caminho de
teste, e é obrigatório nele: um registry global compartilhado entre
testes é contaminação de estado que aparece como falha num outro teste
qualquer.

## Consequências

- `K1` introduz o primeiro caso de **escopo por guild** na API. Quando
  a rotas de registro (`PUT /applications/:id/commands`) forem
  montadas, `guild` vira segmento de URL, e não há caminho por ele no
  `RESTClient` hoje — é escopo novo na camada REST, não só no
  decorator.
- `K2` acopla dois sinais: `cache="cached"` só funciona com
  `Config.cache` tendo `messages > 0`. É aceito, e precisa estar
  escrito no docstring do argumento — senão é a pergunta mais
  frequente da biblioteca.
- `K6` mantém o dispatcher determinístico por padrão, que é o que
  torna os testes de ordem possíveis.
- `K12` exige a fixture `pytest` que cria um `Client(registry=...)`
  novo por teste, listada em `ideias/12` §9 como mitigação do risco
  "registry global esconde estado em teste".

## Alternativas consideradas

| Decisão | Por que não |
|---|---|
| K1: `global_scope=True` só | Cobriria um caso e não os outros dois; `guild=` é o que permite testar sem esperar propagação de 1 hora |
| K1: `scope="global"` | String sem `Literal` não é checada, e dois parâmetros dão erro melhor quando passados juntos |
| K2: `StrEnum CacheRequirement` | Verboso para o argumento mais repetido dos decorators de responder |
| K6: default `concurrent` | Inverteria uma semântica já construída e testada; `Client.spawn` já cobre o paralelismo |
| K10: chamar `on_not_found` | Um só caminho para "ninguém atendeu", ao custo de expor aviso ao usuário final por engano |

## Referências

- `ideias/12-encaixe-no-projeto.md` §7 — as 12 perguntas originais
- `ideias/07-responders.md` §5 — o que `cache=` controla de verdade
- `ideias/09-emit-responder.md` §2 — o retorno `bool` e o `force`
- `docs/decisions/0006-event-dispatch.md` — por que o dispatcher é
  sequencial, que K6 não muda
- `docs/decisions/0008-cache-and-state.md` — o `CachePolicy` que K2
  não pôde reusar
