# Decisões de arquitetura

Cada arquivo registra uma decisão técnica que afeta a API pública ou a
estrutura do projeto. Formato: contexto, decisão, consequências,
alternativas consideradas.

| # | Decisão | Status |
|---|---|---|
| [0001](0001-http-transport.md) | Transporte HTTP: httpx | aceita |
| [0002](0002-websocket-transport.md) | Transporte WebSocket: websockets | aceita |
| [0003](0003-data-models.md) | Modelos de dados: dataclasses | aceita |
| [0004](0004-build-order.md) | Ordem de construção: REST → Gateway | aceita |
| [0005](0005-gateway-reconnect.md) | Reconexão do Gateway: classificação de close code | aceita |
| [0006](0006-event-dispatch.md) | Eventos: payload tipado e política de dispatch | aceita |
| [0007](0007-api-layer.md) | Camada `api/`: vocabulário sobre a mecânica REST | aceita |
| [0008](0008-cache-and-state.md) | Cache local e estado: `cache/` + `state/` | aceita |
| [0009](0009-command-responder-surface.md) | Superfície de comandos, eventos e responders: K1–K12 | aceita |
| [0010](0010-client-options.md) | `Options` como campos do `Config`; handlers sempre assíncronos | aceita |
| [0011](0011-command-registry.md) | Chave do registry `(type, name, scope)`; singleton por payload | aceita |
| [0012](0012-contextos.md) | Contextos: um dono por pergunta; `InteractionContext` dono do estado | aceita |
| [0013](0013-router-syntax.md) | Sintaxe de rota e prioridade por peso de segmento | aceita |
| [0014](0014-converters.md) | Conversores `fn(raw, ctx)`; cache → REST → `ConversionError` | aceita |
| [0015](0015-components.md) | Builders `frozen`; `MessageFlags`; V2 explícito | aceita |
| [0016](0016-interaction-state.md) | Máquina de 4 estados; dono é o `InteractionContext` | aceita |
| [0017](0017-middleware-errors.md) | Middleware `(ctx, block)`; `block` impede tudo; hierarquia de erros | aceita |
| [0018](0018-command-sync.md) | `sync()` bulk PUT + diff; lacuna REST do `K1` | aceita |
| [0019](0019-discovery-bootstrap.md) | `bootstrap` ordena por profundidade; `*_mod.py` mantido | aceita |
| [0020](0020-events.md) | `EVENT_PAYLOADS` + instantânea do `old`; `@event` com `EventContext` | aceita |
| [0021](0021-autocomplete.md) | Autocomplete: B tem prioridade; empate é erro | aceita |
| [0022](0022-context-menus-transport.md) | Context menus por `type=`; transporte por retorno e por `ctx.state` | aceita |
| [0023](0023-responder-parity.md) | Paridade de interação com o discord.js; `ResponderType` StrEnum; `defer(ephemeral)` em componente é erro | aceita |
| [0024](0024-components-block.md) | Bloco de componentes: `uploads.py`/`choices.py`; `era` como `ClassVar`; serialização chega ao HTTP | aceita |
| [0025](0025-events-payloads-snapshot.md) | `EVENT_PAYLOADS` vale para `client.on`; correção do `ready`; `TypingStart`/`VoiceState` e cache de voz | aceita |
| [0026](0026-interaction-routing-commands.md) | `@command`, `CommandInstance.run` e o roteador de `INTERACTION_CREATE`; `Client(registry=)`, `run()`, `_tasks` | aceita |
| [0027](0027-discovery-bootstrap-impl.md) | `bootstrap` é `async`; resolução sem efeito colateral; sintaxe do glob fechada | aceita |
| [0028](0028-command-scope-deferred.md) | Escopo do `@command` quando o decorator não declara; `deferido` + `reescopiar` no `start()` | aceita |
| [0029](0029-on-not-found-arity.md) | `on_not_found(ctx)` — um argumento só, nos dois ramos | aceita |
| [0030](0030-per-command-error-handlers.md) | `on_error` por comando passa a ser lido; `on_not_found` sai da superfície do decorator | aceita |

As 12 decisões de API pendentes (K1–K12) foram fechadas no `0009` —
eram o que a Fase 4 precisava saber antes de codar. As vinte e uma
seguintes (`0010`–`0030`) fecham o resto da superfície: construtor,
registry, contextos, rota, conversores, componentes, máquina de
estados, middleware/erros, sync, bootstrap, eventos, autocomplete,
context menus, a paridade com o discord.js, o bloco de componentes, os
eventos com `EVENT_PAYLOADS`, o roteamento de interação, o `bootstrap`,
o escopo adiado, a assinatura do `on_not_found` e os handlers por
comando.

As seis últimas (`0025`–`0030`) foram levantadas ao codar os blocos 7–9:
cada uma encontrou uma contradição entre duas decisões já aceitas — ou
entre uma decisão e o código que deveria tê-la implementado — e a
resolveu por escrito, em vez de deixar o código escolher em silêncio.
`0029` e `0030` são as primeiras a corrigir o próprio `src/`: um grep
mostrou dois parâmetros documentados sem leitor nenhum, e duas
assinaturas diferentes para a mesma opção.

Cada uma passou pelo conselho de 22 perfis; o veredito e a divergência
preservada estão no rodapé de cada registro. A ordem de implementação
dos itens 8–18 de `ideias/12` §5 continua aberta — depende de o
registry estar maduro antes da modularização.
