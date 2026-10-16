# 0008 — Cache local e estado: `cache/` + `state/`

## Contexto

A arquitetura §11 diz que a biblioteca não pode exigir cache e
descreve `cache/` e `state/` como pacotes da Fase 3. O `0004` colocava
o cache na Fase 5; o README registrou "falta na Fase 3". A escolha foi
construir agora — junto com os modelos e o dispatcher, que são quem
alimenta — em vez de depois, quando a API pública já estaria congelada
em volta de um `client.cache` que ainda não existe.

O problema de fundo não é guardar, é **atualizar**. O Discord tem três
comportamentos que tornam isto mais difícil do que um dict:

1. **Manda objetos pela metade.** `MESSAGE_UPDATE` de uma edição em
   embed vem sem `content`; `GUILD_UPDATE` vem sem os arrays de
   organização; `GUILD_MEMBER_UPDATE` traz `deaf?` e `mute?` como
   opcionais.
2. **Não manda remoção para quase nada.** Não existe `USER_DELETE`. Não
   existe `CHANNEL_DELETE` para os canais de um servidor do qual o bot
   saiu. `MESSAGE_DELETE` raramente chega.
3. **Manda arrays inteiros sem avisar.** `GUILD_CREATE` traz todos os
   membros de uma vez — 100k numa guild grande —, e só depois o resto
   da sessão manda deltas.

Qualquer uma das três, mal tratada, produz o mesmo sintoma: um `get()`
que devolve `None` ou valor velho para sempre, que parece (e é
tratado como) política desligada.

## Decisão

### Escopo: `cache/` + `state/`, sem benchmark

Só os dois pacotes, com testes unitários. Benchmarks e números de
detenção ficam na Fase 5 — medir agora seria fixar um alvo antes de
ter o que medir, e os testes já cobrem o que é correção (ordem, teto,
índice), não velocidade.

### O protocolo é síncrono

`CacheProtocol` não tem `await` em lugar nenhum, e o dispatcher não
faz I/O.

Um `await` em `get()` seria cobrado de **todo** handler, do usuário e
de dentro da biblioteca, e transformaria um caminho que hoje é só
parse e dict em algo que pode suspender. Quem quiser Redis ou
Memcached constrói a camada por fora, como discord.js e discord.py
fazem — o protocolo existe justamente para ser implementável por fora.

A consequência prática é que um backend assíncrono teria que espelhar
(a seguir) em memória, o que é uma escolha do implementador, não um
defeito do contrato.

### Remoção: híbrida, decidida campo a campo

Duas mecânicas, e quem usa qual é a natureza do evento:

| | Mecânica | Por quê |
|---|---|---|
| guild, canal, cargo, membro | invalidação por evento | O gateway **manda** o evento de remoção (`GUILD_DELETE`, `CHANNEL_DELETE`, `GUILD_ROLE_DELETE`, `GUILD_MEMBER_REMOVE`) |
| usuários, mensagens | LRU com teto | Não há evento de remoção, ou ele raramente chega |

`bool` em `CachePolicy` significa "tem evento de remoção" (o limite é a
sessão); `int` significa "não tem" (o limite é o número). `0` é
desligado, e não "teto de zero lugares" — quem lê `messages=0` tem que
entender `allows()` falso, não `limit_for() == 0` coexistindo com
habilitado.

A divisão não é cosmética: é a razão de `guilds=True` ser seguro e
`users=True` ser uma bomba de memória.

### Ligado por default, com dois opt-in

`CachePolicy()` guarda `guilds`, `channels`, `roles` e `users`. São os
quatro tipos cuja entrega o gateway não depende de intent nenhum e que
são pequenos por natureza.

Os dois que ficam de fora:

- **`members: bool = False`** — `GUILD_CREATE` manda a lista inteira de
  uma vez. Uma guild de 100k membros vira 100k objetos no primeiro
  evento da sessão, e não é o bot que escolheu.
- **`messages: int = 0`** — só cresce, e o histórico honesto vem da REST
  com cursor, não de sobras de evento.

`CachePolicy.full()` liga os dois (`members=True`, `messages=2_000`)
para quem quer tudo. `CachePolicy.disabled()` desliga tudo.

**`enabled=False` sobrepõe todos os campos.** Um flag que os campos
individuais sobrescrevem não é um flag, é sugestão — e quem escreve
`CachePolicy(enabled=False, guilds=True)` está se enganando sobre o
que vai acontecer.

### `state/` não duplica a sessão do Gateway

`gateway/session.py` tem `SessionInfo` (session_id, sequence,
resume_url): estado de **transporte**, existe para o `RESUME` funcionar.
`state/connection_state.py` tem `me` e o que o Discord contou: estado
de **domínio**.

Seria a segunda fonte de verdade que a arquitetura §1 proíbe, e a
divergência seria o bug menos diagnosticável da biblioteca — um
`session_id` diferente entre os dois módulos não produz erro, produz
`RESUME` rejeitado sem causa aparente.

`SessionInfo` responde "de onde continuo?"; `ConnectionState` responde
"quem eu sou e o que já chegou". São perguntas diferentes.

### Três papéis, três arquivos

| Arquivo | Papel |
|---|---|
| `state/connection_state.py` | `ConnectionState` — lê, escreve e sabe a chave. É o `client.cache` |
| `state/guild_state.py` | `GuildState` — visão de uma guild já escopada |
| `state/event_updates.py` | `EventUpdater` — o que um evento **significa** |

A divisão é entre **o quê** e **onde**. `event_updates` decide que
`GUILD_MEMBER_REMOVE` significa "tira este membro desta guild";
`connection_state` sabe que a chave é `member_key(guild_id, user_id)` e
que o agrupamento é `str(guild_id)`.

Repartir o conhecimento da chave seria o erro que não se vê: a chave
errada não levanta exceção, devolve `None` — que é exatamente o
sintoma de política desligada.

`GuildState` existe porque `members`, `roles` e `channels` só fazem
sentido dentro de um servidor. Torná-los `members(gid)` no objeto
grande daria dois nomes para a mesma coisa, e duas formas de divergir.

### `me` fica fora do repositório

`ConnectionState._me` é campo próprio, não uma entrada do cache.

O repositório de usuários é LRU, sem evento de remoção, e numa sessão
longa o próprio bot seria derrubado por cem mil mensagens de
terceiros. "Quem eu sou" não é uma pergunta que pode ter resposta
vazia.

O preço é explícito: `get_user(id_do_bot)` devolve `None` até o bot
aparecer num payload de verdade (uma mensagem que ele mesmo mandou,
por exemplo). A regra é uma só — `set_me` é "você é este", e não "você
o viu".

### A regra de merge é presença no payload, não diferença de default

`from_payload` **não** distingue ausente de `False`: campo que não veio
vira `False`, `()` ou `None`. Então quem compara modelo-com-modelo
concluiria que um campo apagado foi alterado — o oposto do que houve.

Quem compara é o payload bruto. Campo cujo nome está no JSON é campo
que o Discord falou; os outros ficam como estavam.

É a mesma regra de sempre — *ausente não é valor* —, aplicada do lado
de dentro da atualização em vez do lado do parsing.

**`_RENOMES`** cobre o caso em que Discord e model discordam do nome do
mesmo campo (`edited_at` ← `edited_timestamp`, `positions_new` ←
`positions`). Sem isto, a data de edição de uma mensagem ficaria antiga
para sempre num campo que quase todo código olha.

Ficam de fora os campos derivados de nó aninhado (`Channel.archived`
sai de `thread_metadata`): aqueles não têm outro nome, têm outro
lugar, e saber a árvore exigiria que cada model declarasse como o
payload é estruturado. É um limite conhecido, documentado no próprio
`_channel_update` — e mitigado porque `THREAD_*` é tratado
explicitamente.

### O cache é alimentado antes dos handlers

`Client._dispatch` faz: updater → `_ready.set()` → `dispatcher.dispatch`.

A ordem é o ponto. Se o handler rodasse antes, todo
`cache.get_member()` dentro dele veria o estado do **evento anterior** —
e o bug não apareceria em teste unitário nem em conversa: só sob
carga, e sumiria quando alguém parasse o bot para olhar.

A falha do updater é logada e ignorada, com o mesmo contrato dos
handlers: exceção é isolada, `CancelledError` propaga. O updater não
engole nada sozinho de propósito — quem decide se é grave é quem está
no meio da entrega, e `Client._dispatch` é esse lugar.

### `REGISTRY` não muda

`events/dispatcher.py::REGISTRY` decide **o que o handler recebe**, e é
um contrato de entrega que não muda porque o cache passou a guardar
coisa.

`event_updates` tem mapa próprio (`_PARSERS` lógico, no `apply`).
`GUILD_MEMBER_ADD` não está no `REGISTRY` (handlers recebem o dict
cru, decisão do 0006) mas o cache precisa do `Member`.

Misturar os dois faria o cache parar de funcionar no dia em que um
evento ganhar ou perder parser lá.

### Chaves são `str`, não tupla

`member_key(10, 20) == "10:20"`.

Uma tupla `(guild, user)` só existe dentro de um dict; string atravessa
qualquer backend sem tradução, e `:` é o separador — `member` e `role`
carregam a guild na chave, `user`, `guild`, `channel` e `message` são
globais porque o ID deles é.

ID `int` e `str` produzem a mesma chave: o Discord manda snowflake como
string, quem lê de modelo tem `int`, e chaves diferentes fariam um
`get()` com o tipo errado devolver `None` sem dizer por quê.

### O `group` existe para enumeração em O(1)

`CacheProtocol.set(..., group=...)` grava junto um índice por guild, e
`group_values(kind, guild)` devolve os filhos sem varrer todos os
tipos. Um guild com 100k membros não pode ser listado custando 100k ×
todos os servidores.

O índice é um `dict[str, None]` (set ordenado por inserção — ordem de
chegada é a única estável, o Discord não garante a do array), e grupos
que ficam vazios são removidos: um servidor que o bot saiu não pode
deixar dict vazio e uma ordem fantasma para sempre.

### `get()` conta falta; `pop()` não

- `get()` conta miss mesmo quando a política desligou o tipo. Quem
  chamou `get_member()` recebeu `None`, e a métrica tem que dizer
  isso. Um `hit_rate` ruim porque a política não cobre o tipo é o
  sintoma certo — e some assim que alguém ligar o campo.
- `pop()` não conta miss. `MESSAGE_DELETE` de mensagem nunca cacheada é
  o caso normal; punir isto faria a métrica culpar o cache por estar
  incompleto, que é o estado dele por design.

### `CacheStats.hit_rate` é `None` quando ninguém consultou

`0/0` não é 0%, é "não sei". Devolver `0.0` diria que tudo falhou, e
quem lê a métrica concluiria o contrário do que houve.

`reset()` zera contadores mas **não** `sizes`: apagar a contagem de
acertos não esvazia o cache, e reportar `size == 0` logo depois seria
mentira sobre quanto está na memória.

`snapshot()` devolve cópia — quem guarda o retrato para comparar antes
e depois não pode ver os números mudarem dentro dele.

## Consequências

- `client.cache` existe desde a construção, como `client.api`. Um
  handler registrado fora do `async with` captura no closure.
- `Config.cache` é a política. Trocar depois de ligar não desfaz o que
  já entrou — por isso é config, e não setter.
- `ConnectionState` é síncrono. Nenhum handler precisa de `await` para
  ler o cache.
- `None` de um `get` é o estado normal, e tem três significados
  distintos (política desligada, ainda não chegou, não existe mais) —
  `cache.stats` é quem distingue.
- O índice de grupo é memória extra (~um dict por guild por tipo
  agrupado). Trocado por varredura, `group_values` passaria a custar
  `len(todos_os_members)` por chamada.

## Escopo

### Pacotes novos

- `src/kryncord/cache/` — `keys.py`, `stats.py`, `policy.py`,
  `protocol.py`, `memory.py`, `__init__.py`
- `src/kryncord/state/` — `guild_state.py`, `connection_state.py`,
  `event_updates.py`, `__init__.py`

### Alterações existentes

- `config.py` — campo `cache: CachePolicy`
- `client.py` — `_state`/`_updater` no `__init__`, propriedade `cache`,
  `_update_cache()` chamado por `_dispatch` com `try/except` + log
- `__init__.py` — exporta `CacheKind`, `CachePolicy`, `CacheProtocol`,
  `CacheStats`, `MemoryCache`, `ConnectionState`, `GuildState`

### O que **não** mudou

- `events/dispatcher.py::REGISTRY` — intocado, por decisão.
- Nenhum model ganhou campo. `Member` e `Role` seguem sem `guild_id`:
  quem sabe a guild é quem lê o evento (`event_updates`), não o modelo.

### Bugs que os testes pegaram

1. **`members` desligado engolia o `set` em silêncio.** Três testes de
   agrupamento passavam com `== ()` por motivo nenhum — asserção
   vacua. Conserto: fixture com a política ligada e asserção positiva
   antes da negativa.
2. **Canal aninhado no `GUILD_CREATE` sem `guild_id`.** O agrupamento
   sairia `None` e a guild não enxergaria os canais que ela mesma
   mandou. Conserto: `_canal_no_guild` completa pelo contexto — o array
   está dentro do objeto da guild, o contexto é a resposta.

   **Confirmado ao vivo, e não era cautela:** contra o gateway real,
   `24/24` canais de um `GUILD_CREATE` vieram sem `guild_id`. Sem o
   conserto, a guild apareceria com zero canais num evento que os manda
   todos de uma vez.

### Verificação ao vivo

`bot testes/smoke_cache.py` liga um bot de verdade e confere o cache
dentro do handler — a ordem updater→handler é testável só assim,
porque num teste unitário com o transport fake os dois rodam na mesma
task.

Resultado registrado (gateway `gateway-us-east1-c.discord.gg`,
2026-10):

```
READY ok     — cache.me = Kryn testes (id 1461827877627629620), guilds em cache = 1
GUILD_CREATE — Kryn: 31 cargo(s), 24 canal(is), 1 membro(s)
payload cru  — 24/24 canal(is) vieram SEM guild_id
stats        — acertos=2 faltas=0 remoções=0 taxa=1.0
retrato      — {'me': 1461827877627629620, 'guilds': 1, 'channels': 24, 'users': 1}
```

Três coisas que só o gateway real prova: que `me` é preenchido, que a
visão da guild chega povoada **dentro** do handler, e que o payload
real não traz `guild_id` nos canais.
3. **Merge não achava `edited_timestamp`.** O campo do model é
   `edited_at`; procurar `edited_at` no JSON nunca encontra. Conserto:
   `_RENOMES`.
4. **Chave órfã no índice quando o LRU derrubava.** O caminho é
   inalcançável pela API pública hoje (só `users` e `messages` têm teto
   e nenhum dos dois recebe grupo), mas o armazenamento não podia
   assumir isso — senão a política vira armadilha no dia em que um
   tipo ganhar teto.

## Alternativas consideradas

### Entrega por async iterator (um `events`/`stream()`)

Rejeitado. O projeto já escolheu callback (`EventHandler`) no 0006,
e dois caminhos de entrega para o mesmo fluxo seria uma divergência
esperando para acontecer.

### `Message.clean_content` e leituras derivadas

Rejeitado até aqui (decisão do 0006). `clean_content` precisa de um
cache para ser honesto — e com ele agora existe, continua sendo
questão de API, não de cache.

### Unificar `REGISTRY` e o mapa do updater

Rejeitado, pelas razões acima: dois contratos com interesses
diferentes.

### Modelos ganhando `guild_id` em `Member`/`Role`

Rejeitado. Dentro de um `GUILD_CREATE` a lista de membros vem dentro do
objeto da guild e não diz de qual é — o campo seria `None` no caso mais
comum, que é a definição de mentira por omissão. O Discord completa
`guild_id` nos eventos soltos, e em ambos os casos quem sabe é quem
leu o evento.

## Referências

- `docs/internals/architecture.md` §`cache/` e `state/` (linha 543) e §11
  Cache e memória (linha 656)
- `docs/decisions/0006-event-dispatch.md` — por que o `REGISTRY` não
  muda e por que `from_payload` devolve `None`
- `docs/decisions/0003-data-models.md` — modelos congelados, e por que
  isso torna o merge obrigatório
- Documentação do Discord: gateway events
  (`https://discord.com/developers/docs/events/gateway-events`)
