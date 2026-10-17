# Changelog

Formato em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
numeração em [SemVer](https://semver.org/lang/pt-BR/).

## [Unreleased]

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

[Unreleased]: https://github.com/KrynCord/kryncord/compare/v0.2.0b2...HEAD
[0.2.0b2]: https://github.com/KrynCord/kryncord/releases/tag/v0.2.0b2
[0.2.0b1]: https://github.com/KrynCord/kryncord/releases/tag/v0.2.0b1
[0.1.0b2]: https://github.com/KrynCord/kryncord/releases/tag/v0.1.0b2
[0.1.0b1]: https://github.com/KrynCord/kryncord/releases/tag/v0.1.0b1
