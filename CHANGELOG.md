# Changelog

Formato em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
numeração em [SemVer](https://semver.org/lang/pt-BR/).

## [Unreleased]

## [0.3.0b1] — 2026-10-17

O módulo Gateway completo, com paridade comportamental com o
`@discordjs/ws` (v2.0.2) — a matriz de 54 itens e as divergências
deliberadas estão no dossiê `update/gateway/`. Cinco fases, um commit
cada, gates verdes em todas.

### Adicionado

- **Fase A — teto de `READY` e budget de envio.**
  `ready_timeout` (15s, `GatewayConfig`) aplicado de verdade: o `READY`
  ou `RESUMED` que não chega vira `GatewayError` e o ciclo de
  recuperação tenta de novo — antes, um servidor que aceitasse o socket
  e ficasse calado deixaria o bot ligado para sempre. Ops importantes
  (1 heartbeat, 2 identify, 6 resume) não contam no budget de 115
  frames, e a janela reseta a cada (re)connect, como no discord.js.
- **Fase B — Request Guild Members (op 8).**
  `Client.request_guild_members()` / `GatewayClient.request_guild_members()`:
  o `guild.members.fetch()` em payload cru — pede os membros de uma
  guild pela conexão e devolve a soma dos `GUILD_MEMBERS_CHUNK`.
  Nonce de até 32 chars (gerado quando ausente), prazo de 120s
  renovado a cada chunk, teto de 5 pedidos simultâneos (melhoria sobre
  o discord.js), conclusão pelas três regras do `GuildMemberManager`.
  Erros novos: `MemberRequestError`, `MemberRequestTimeout`,
  `MemberRequestRateLimited` (com `retry_after`), `TooManyMemberRequests`.
- **Fase C — Presence em runtime (op 3).**
  `Client.update_presence()` / `GatewayClient.update_presence()`: status,
  atividades e `afk` sem reconectar, com teto client-side de 5 updates
  por 20s — quem manda mais paga a espera, em vez de ter o update
  sumindo sem aviso (regra §13). `status` validado na cara, listando as
  opções do Discord.
- **Fase D — multi-shard.**
  `GatewayManager`: N shards em um processo, shards em paralelo sem
  stagger (como o `SimpleShardingStrategy`), **um** throttler de
  identify compartilhado (bucket = `shard % max_concurrency`), latência
  = média das shards, pronto = todas prontas. `Client` ganha
  `shard_ids` e `gateway_information`; quem pede `shard_ids` sem a
  informação leva um fetch de `GET /gateway/bot` na véspera de
  conectar (`session_start_limit` envelhece). Rota REST
  `client.api.gateway.bot()` → `GatewayBotInfo`/`SessionStartLimit`.
  Falha fatal numa shard fecha o manager inteiro e propaga o erro
  original — bot meio ligado é pior que desligado.
- **Fase E — compressão `zstd-stream`.**
  Extra `kryncord[zstd]` (`zstandard>=0.22`); sem a lib, o pedido
  falha no primeiro frame dizendo o comando de instalação. Cada frame
  WS é um frame zstd completo, como no discord.js.

### Alterado

- `op 9` (`INVALID_SESSION`) não dorme mais 1–5s antes de retomar: o
  backoff da política de reconexão e o throttler de identify já dão o
  anti-thrash — o `@discordjs/ws` removeu a espera pelo mesmo motivo.
- `Client.start()` devolve quando **todas** as shards estão prontas;
  `client.gateway` agora é o `GatewayManager` (com uma shard só, ele
  tem exatamente uma — `ready`, `latency` e `close` seguem iguais).
- `_unless_closing` generalizado: o `close()` devolve na hora não só
  do backoff entre tentativas, mas também da espera da janela do
  throttler do identify.

### Removido

- `GatewayConfig.invalid_session_wait`, `GatewayConfig.identify_timeout`
  e `GatewayConfig.resume_timeout` — eram validados e nunca lidos por
  nenhum código (a espera do op 9 saiu justamente por isso, e os
  dois últimos nunca tiveram efeito).

## [0.2.0b3] — 2026-10-17

A latência do Gateway vira superfície pública — o número que o
`client.latency` do discord.py (segundos) e o `client.ws.ping` do
discord.js (ms) mostram no `/ping`, que aqui não tinha como ler.

### Adicionado

- `Client.latency` e `GatewayClient.latency` — round-trip do
  heartbeat (``op 1`` → ``ACK``) em ms, medido no relógio monotônico
  da `HeartbeatState`. `None` antes do `start()` e antes do primeiro
  ACK: zero seria mentira sobre algo que não foi medido.

## [0.2.0b2] — 2026-10-17

Correção de caminho do `api` no despacho. O `Client` entrega o
`DiscordAPI` **raiz** aos despachos, e ele não tem `respond` — a
primeira `/ping` ao vivo morria com `AttributeError` dentro da
resposta. Passou pela suíte inteira porque o duplo de `api` dos
testes era plano (`TestApiRealNoDespacho` prende isto agora, com o
`DiscordAPI` real sobre transporte falso).

### Adicionado

- `kryncord.api.interacoes_de` — o `InteractionsAPI` de um `api`,
  seja o `DiscordAPI` raiz (o `client.api`) ou o próprio namespace.
  Os três ramos de despacho (`dispatch_application_command`,
  `dispatch_autocomplete`, `dispatch_responder`) normalizam na
  entrada; os contextos seguem guardando o namespace.
- `TestApiRealNoDespacho` — despacho ponta a ponta com `DiscordAPI`
  real: comando → tipo 4, componente → tipo 7, autocomplete → tipo 8
  (com handler e no fallback vazio).
- `pythonpath` do pytest inclui `src` — o teste local roda contra a
  árvore de trabalho mesmo com o wheel instalado no mesmo
  interpretador (a CI já rodava assim, por causa do `-e`).

### Mudado

- `InteractionsAPI.callback` manda `auth=False`: o token da interação
  vai na URL, e `Authorization: Bot` junto seria dupla credencial que
  mascara qual falhou num 403 — o mesmo que o discord.js faz em todo
  `interactionCallback`.

## [0.2.0b1] — 2026-10-17

A migração **breaking** da superfície de interações (ADR 0031): os
contextos genéricos saem, as interações tipadas entram. Cada troca
está listada abaixo — é uma passada de grep no código do bot, não uma
migração em duas etapas.

### Adicionado

- **API de interações tipadas (ADR 0031)** — as classes que o handler
  recebe: `CommandInteraction` (`UserCommandInteraction`,
  `MessageCommandInteraction`, `EntryPointInteraction`),
  `ComponentInteraction` (`ButtonInteraction`, `StringSelectInteraction`,
  `UserSelectInteraction`, `RoleSelectInteraction`,
  `ChannelSelectInteraction`, `MentionableSelectInteraction`,
  `ModalSubmitInteraction`) e `AutocompleteInteraction`.
- Decoradores de componente com entrega tipada: `@button`,
  `@string_select`, `@user_select`, `@role_select`, `@channel_select`,
  `@mentionable_select`, `@modal_submit` — todos açúcar sobre
  `@responder`, mesmo registry.
- Validação de assinatura de handler na importação:
  `HandlerSignatureError` — primeiro parâmetro tem que ser anotado com
  a classe que será entregue (`Any` e protocolo passam; `object` não).
- Estados `InteractionState.COMPLETED` (depois de
  `delete_original_response`) e `EXPIRED` (token de 15 min, calculado
  com preguiça a partir do snowflake; ids sintéticos nunca expiram),
  com `InvalidInteractionState.is_expired()` e os predicados
  correspondentes.
- `docs/api/interactions-architecture.md` e
  `docs/api/interaction-response-methods.md` — as duas referências de
  superfície de interação (reconstituídas da especificação original).

### Mudado

- **Métodos de resposta renomeados**: `reply` → `respond`, `edit` →
  `edit_original_response`, `delete` → `delete_original_response`,
  `fetch`/`fetch_reply` → `fetch_original_response`, `follow_up` →
  `followup`, `send_modal` → `open_modal`. São os nomes nos dois lados
  — `InteractionContext` interno e a interação tipada.
- `InteractionState.MODAL` → `MODAL_OPENED`; `delete_original_response`
  passa a transicionar para `COMPLETED` a partir de `DEFERRED` e
  `ANSWERED`.
- **Sintaxe de rota do `custom_id`**: `{param}` obrigatório,
  `{?param}` opcional, `**`/`**{nome}` wildcard — com o parâmetro
  permitido **dentro** do segmento (`/produto:{product_id}:comprar`).
  `build_custom_id` valida valor vazio além do que já validava.
- `@event` passa a entregar **só o payload** — mesmo contrato do
  `client.on`; aridade esperada deixa de contar contexto. Middleware e
  `on_error` recebem o `EventFrame` interno
  (`kryncord.events.context`, não exportado).
- `dispatch_application_command` não aceita mais `cache=`.

### Removido

- **`CommandContext`, `ResponderContext`, `EventContext` e
  `AutocompleteContext`** — os contextos genéricos não existem mais,
  sem aliases de depreciação: migração de grep, não de dois anos.
- **`InteractionStateError`** → `InvalidInteractionState`.
- **Sintaxe de rota antiga** (`:param`, `?:param`, `**:nome`):
  `parse_rota` recusa com `ResponderDefinitionError` citando a troca.
- `EventDispatcher.add(..., with_context=)` e `EventEntry.with_context`
  — não há mais caminho de contexto na frente do payload.
- `commands/context.py` e `responders/context.py` (módulos apagados).

## [0.1.0b2] — 2026-10-16

Versão de documentação e metadados: nenhum código de runtime mudou.
Publicada porque o PyPI mostra a descrição e o autor **do pacote
enviado** — a página de `0.1.0b1` ficou com o README antigo e com
`kruldevb` no campo de autor, e isso não se corrige reenviando a mesma
versão.

### Adicionado

- README reescrito como entrada do projeto, bilíngue: instalação,
  início rápido, exemplos de comando/cache/erros, tabela de
  documentação e a seção de limites que a biblioteca não garante.
- `docs/README.md`, com o índice e a ordem de leitura da documentação.
- `docs/guides/publication.md` — passo a passo de publicação.

### Mudado

- Documentação da raiz reorganizada em `docs/`: `api/`, `internals/`,
  `reference/` e `guides/`, com as referências cruzadas dos ADRs
  atualizadas.
- Metadado de autor no `pyproject.toml` passa a ser `Gustavo Silva`,
  que é o que o `LICENSE` declara.
- `publish.yml` fica com gatilho manual (`workflow_dispatch`) até o
  Trusted Publishing existir; religar a gatilho por tag está escrito
  no próprio arquivo.

### Corrigido

- `pytest` (o binário) falhava na CI com
  `ModuleNotFoundError: No module named 'tests'` — `python -m pytest`
  escondia o problema porque colocava o CWD no `sys.path`. Corrigido
  com `pythonpath = ["."]`.
- Actions de CI atualizadas para os majors atuais, encerrando o aviso
  de Node.js 20 descontinuado.
- Sdist embarcava `base/discord.js` inteiro (9,2 MB); agora é 499 KB
  com uma lista explícita de `only-include`.

## [0.1.0b1] — 2026-10-16

Primeira versão beta pública. O núcleo está de pé — REST e Gateway
próprios, sem dependência de `discord.py`.

### Adicionado

- `Client` e `Config` — ciclo de vida assíncrono, `async with` fecha a
  conexão sozinho.
- Camada REST própria (`client.api`) com rate limit, retries e multipart.
- Camada Gateway: Identify, heartbeat, ACK, reconexão e retomada de
  sessão.
- Payloads entregues **interpretados**: `Message`, `Guild`, `Ready` e
  companhia em vez de `dict`.
- Roteamento de comandos, interações e responders.
- Cache opcional por política (`CachePolicy`) com estatísticas de hit
  rate.
- Tipagem completa (`py.typed`) e `mypy --strict` no código inteiro.

### Conhecido

- O Discord não manda `guild_id` nos canais do `GUILD_CREATE` — a
  biblioteca preenche a visão da guild por conta própria (verificado ao
  vivo: 24/24 canais sem o campo).
- `MESSAGE_CONTENT` é privileged: precisa ser ligado no portal do
  Discord antes de pedir o intent.

[Unreleased]: https://github.com/KrynCord/kryncord/compare/v0.2.0b3...HEAD
[0.2.0b3]: https://github.com/KrynCord/kryncord/releases/tag/v0.2.0b3
[0.2.0b2]: https://github.com/KrynCord/kryncord/releases/tag/v0.2.0b2
[0.2.0b1]: https://github.com/KrynCord/kryncord/releases/tag/v0.2.0b1
[0.1.0b2]: https://github.com/KrynCord/kryncord/releases/tag/v0.1.0b2
[0.1.0b1]: https://github.com/KrynCord/kryncord/releases/tag/v0.1.0b1
