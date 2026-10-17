# 0031 — Interações tipadas: fim do `ctx` genérico

## Contexto

O `0012` estabeleceu "um dono por pergunta" e entregou quatro contextos
genéricos ao autor do bot: `CommandContext`, `ResponderContext`,
`EventContext` e `AutocompleteContext`. A superfície pública passou a
girar em torno do `ctx`, e três coisas nele envelheceram mal.

**O primeiro argumento não dizia o que é.** `async def ping(ctx)` não
distingue comando de botão de modal — e o que o `ctx` *permessa* mudava
com isso, em silêncio: `update()` existe em componente e não em comando,
`open_modal()` existe nos dois, `autocomplete()` só em autocomplete.
Sem a classe na assinatura, o editor e o mypy não veem nenhuma
restrição, e o erro aparece no clique, como `AttributeError` do meio do
handler.

**Os nomes da resposta eram de outro verbo.** `reply`, `edit`,
`follow_up`, `send_modal`, `delete` — superfície que o `0023` já
comparava com a do discord.js e que contradizia o próprio vocabulário
interno (`respond`, `followup`).

**A entrega não era determinística.** O que o handler recebia dependia
de como o registro interpretava a anotação — dois caminhos para a mesma
pergunta, e a anotação escolhendo o que chega em vez de só *declarar* o
que chega. Dois símbolos para a mesma coisa é como se cria divergência
(`0011`), e aqui era no lugar mais lido da superfície.

Somou-se a isso a sintaxe de rota `:param`/`?:param` (`0013`), que só
aceitava parâmetro no começo do segmento — `produto:42:comprar` era
literal; e o `@event` recebendo `EventContext` na frente do payload
(`0020`), quando o `client.on` não recebia — dois contratos para a
mesma tabela.

A decisão veio prescrita por especificação externa (os dois documentos
de API de interação que este ADR reconstitui em
[`docs/api/interactions-architecture.md`](../../docs/api/interactions-architecture.md)
e
[`docs/api/interaction-response-methods.md`](../../docs/api/interaction-response-methods.md)),
segunda de um plano de 9 fases aprovado para migração da biblioteca e
do bot.

## Decisão

### 1. Os quatro contextos genéricos não existem mais

Remoção **breaking, sem aliases de depreciação**. Os nomes saem de
`kryncord.__all__`, dos subpacotes e do código. Deixar os nomes
antigos como alias seria manter dois símbolos para a mesma coisa —
exatamente o problema que o `0011` proibiu — e uma migração de API
pública se resolve em uma passada de grep, não em dois anos de
sombra.

| Antes | Depois |
|---|---|
| `CommandContext` | `CommandInteraction` (`UserCommandInteraction`, `MessageCommandInteraction`, `EntryPointInteraction`) |
| `ResponderContext` | `ComponentInteraction` (`ButtonInteraction`, selects, `ModalSubmitInteraction`) |
| `AutocompleteContext` | `AutocompleteInteraction` |
| `EventContext` | (sem substituto público — ver §6) |

### 2. A classe entregue vem do registro, nunca da anotação

O decorator/registry decide: `@command` CHAT_INPUT entrega
`CommandInteraction`, `@button` entrega `ButtonInteraction`,
`@responder` com vários tipos entrega `ComponentInteraction`,
`@inst.autocomplete` entrega `AutocompleteInteraction`. A anotação é
conferida **contra** a entrega, nunca lida para **produzir** a entrega.

### 3. A anotação é validada na importação

Primeiro parâmetro obrigatoriamente anotado; classe esperada ou
subclasse; união com todos os membros aceitáveis; `Any` e protocolo
passam; `object` não (é classe, e classe que não é a entregue está
dizendo que o handler recebe outra coisa). Falhou, é
`HandlerSignatureError` na linha do decorator — a mesma filosofia de
todo o resto da biblioteca (`0011`, `0017`): o erro aparece na
importação, não no clique. O helper mora em
`internal/signatures.py`, num sítio só, para a regra não divergir
entre comandos, componentes e autocomplete.

### 4. Máquina de estados com os nomes da especificação

`InteractionState.MODAL` → **`MODAL_OPENED`** (terminal),
**`COMPLETED`** novo (depois de `delete_original_response`),
**`EXPIRED`** novo, e `InteractionStateError` →
**`InvalidInteractionState`**.

`EXPIRED` é calculado **com preguiça** a partir do snowflake: a
validade do token é 15 minutos (`VALIDADE_TOKEN_MS`), e a comparação é
`criado + 15 min < agora`. Não há timer — nada fica vivo na memória
lembrando de expirar. Ids sintéticos (menores que a época do Discord)
nunca expiram, o que mantém os testes de handcrafted interaction
honestos: eles não fingem ter idade. A propriedade `state` devolve o
estado efetivo (com `EXPIRED`); os predicados leem o interno — expirar
não apaga o que já aconteceu.

### 5. Rota: `{param}` e `{?param}` embutíveis

`/manage/user/{user_id}/{action}`, `/page/{?number}`,
`/produto:{product_id}:comprar`. O param pode aparecer **dentro** do
segmento — a diferença que `:param` não permitia. `**` e `**{nome}`
continuam no fim. A sintaxe antiga (`:param`, `?:param`, `**:nome`)
é **erro na importação**, citando a troca: tratá-la como literal seria
registrar uma rota que nunca casa, sem dizer por quê.

### 6. `@event` recebe só o payload

`client.on` e `@event` passam a ter o mesmo contrato: payload só, uma
tabela, um caminho. O quadro interno (`EventFrame`) continua existindo
— middleware e `on_error` precisam do nome do evento, do client e do
estado compartilhado — mas mora em `kryncord.events.context`, fora de
`__all__`: exportá-lo recriaria o "contexto na frente do payload" que
esta decisão acabou de eliminar.

### 7. `InteractionContext` mantém o nome

É o dono interno do estado e não é a superfície que o autor do bot
escreve. Renomeá-lo compraria churn sem efeito de API — quem o encontra
é quem lê o código da biblioteca, não quem escreve bot. O que mudou foi
o vocabulário dos métodos dele: `respond`, `defer`, `open_modal`,
`followup`, `edit_original_response`, `delete_original_response`.

## Consequências

- **Quebra explícita** para todo código pré-0031: os quatro nomes de
  contexto, os cinco métodos de resposta antigos, `MODAL`,
  `InteractionStateError`, a sintaxe `:param` e o `@event` com contexto
  na frente. O CHANGELOG lista cada troca.
- **`Object` e handlers sem anotação passam a falhar na importação** —
  comportamento novo e desejado, mas é o tipo de coisa que a migração
  do bot encontra primeiro.
- **1677 testes verdes** e `ruff check` limpo em `src/` e `tests/` após
  a migração da suíte (70 arquivos); os testes de estado ganharam casos
  para `COMPLETED` e `EXPIRED`.
- Os ADRs `0012`, `0013`, `0016` e `0020` ficam como registro — esta
  decisão os sobrepõe nos pontos que contradizem, e um ADR não é
  atualizado (`docs/README.md`).
- Duas referências de superfície reconstituídas em `docs/api/`.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Aliases de depreciação (`CommandContext = CommandInteraction`) | Dois símbolos para a mesma coisa — o problema do `0011` recriado na superfície, por dois anos |
| Validação só com `warnings`, sem erro | Um warning num handler que roda é uma mensagem que alguém lê depois do bug; a biblioteca inteira é construída sobre erro na importação |
| Ligar `object` na validação (`object` não mente) | A regra escolhida é classe esperada ou subclasse; `object` dirime o contrato sem dizer nada, e quem quer ignorar a interação anota `Any`, que passa por ser inconfirir — não por ser vago |
| `EXPIRED` com timer agendado | Estado que depende de um `asyncio` vivo na memória; com preguiça a partir do snowflake, o tempo é função do dado |
| Trocar `EXPIRED` por exceção no acesso ao `state` | `state` lido em log/diagnóstico quebraria; o estado é informação, e `InvalidInteractionState` é para quem tenta **agir** |
| Renomear `InteractionContext` junto com o resto | Não é superfície pública de quem escreve bot; churn sem efeito |
| Aceitar `:param` como literal legado | Rota registrada que nunca casa, caindo em `on_not_found` sem dica — pior que recusar |

## Origem e verificação

Este ADR não passou pelo conselho de 22 perfis dos anteriores: a
decisão veio prescrita da especificação do autor e do plano de 9 fases
aprovado, e foi verificada na implementação — suíte inteira verde
(1677 testes), `ruff` limpo, e a migração do bot como Fase 9, com teste
ao vivo. As alternativas acima são as que o plano deliberou durante o
planejamento.

## Divergência preservada

A divergência real ficou entre **contrato honesto** e **contrato
fácil**: o `0025` §3 já havia reduzido a validação de anotação dos
eventos ao que é honesto (`Any`, `object`, ausência e erro de resolução
passam), e esta decisão aplica às interações uma régua mais dura —
anotação obrigatória, `object` rejeitado. As duas convivem sabendo:
eventos são uma tabela de payloads que qualquer handler de assinatura
compatível pode ler; a interação é **um objeto com métodos que existem
ou não existem** nela, e é o único argumento do handler. A anotação do
primeiro parâmetro de interação é a única declaração que o editor tem
para mostrar o que o handler pode chamar — frouxa, ela não mente, mas
também não diz nada.
