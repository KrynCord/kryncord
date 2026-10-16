# Changelog

Formato em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
numeração em [SemVer](https://semver.org/lang/pt-BR/).

## [Unreleased]

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

[Unreleased]: https://github.com/KrynCord/kryncord/compare/v0.1.0b1...HEAD
[0.1.0b1]: https://github.com/KrynCord/kryncord/releases/tag/v0.1.0b1
