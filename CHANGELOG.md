# Changelog

Formato em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
numeração em [SemVer](https://semver.org/lang/pt-BR/).

## [Unreleased]

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

[Unreleased]: https://github.com/KrynCord/kryncord/compare/v0.1.0b2...HEAD
[0.1.0b2]: https://github.com/KrynCord/kryncord/releases/tag/v0.1.0b2
[0.1.0b1]: https://github.com/KrynCord/kryncord/releases/tag/v0.1.0b1
