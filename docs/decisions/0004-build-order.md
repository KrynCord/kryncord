# 0004 — Ordem de construção: REST antes do Gateway

**Data:** 2026-10-11
**Status:** aceita

## Contexto

Com os transportes escolhidos, falta definir a ordem de implementação das
duas camadas centrais. O `KrynCord-ARCHITECTURE.md` §14 sugere REST (Fase 1)
depois Gateway (Fase 2), mas não justifica.

## Decisão

Seguir **REST → Gateway → Core**, a mesma ordem do discord.js.

## Consequências

- A Fase 1 é toda verificável sem rede: `httpx` mockado cobre rate limits,
  buckets, retries e erros.
- O Gateway precisa da Fase 1 — `GET /gateway/bot` retorna a URL de conexão
  e o `session_start_limit`.
- Cada fase tem critério de saída próprio e verificável.

## Ordem

| Fase | Entrega | Critério de saída |
|---|---|---|
| 0 | Fundação: pacote, toolchain, CI | `pytest` verde, `ruff` e `mypy` limpos |
| 1 | REST: rotas, rate limits, buckets, erros | `GET /gateway/bot` real em script de exemplo; testes sem rede |
| 2 | Gateway: connect, identify, heartbeat, resume | bot conecta e loga `READY` |
| 3 | Core: `Client`, `api/`, `models/`, dispatcher | bot responde a `message_create` |
| 4 | Interações: commands, responders, components | os esboços de `ideias/exemplos/` rodam |
| 5 | Cache, estado, benchmarks | políticas de cache e baseline reproduzível |

> **Revisado em 0008.** `cache/` e `state/` passaram para a Fase 3: a
> Fase 5 os receberia depois de a API pública estar congelada em volta
> de um `client.cache` que ainda não existia, e sem os testes pegarem
> os quatro bugs de merge e de índice que apareceram. A Fase 5 ficou só
> com os **benchmarks** — medir antes de ter o que medir fixa um alvo
> arbitrário.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Gateway → REST | Conecta mais cedo, mas sem REST não há `GET /gateway/bot`, e os testes de Gateway seriam mais frágeis (mais I/O real). |
| As duas em paralelo | Mais rápido, mas duas camadas inacabadas ao mesmo tempo dificultam revisar e depurar. |

## Nota

A Fase 3 é a primeira em que o usuário vê "o bot funcionando". Se o
andamento travar, é legítimo pular para o núcleo dela (`client.py` +
dispatcher) antes de completar todos os endpoints da Fase 1 — desde que os
testes de REST já estejam verdes.
