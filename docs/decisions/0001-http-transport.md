# 0001 — Transporte HTTP: httpx

**Data:** 2026-10-11
**Status:** aceita

## Contexto

A KrynCord precisa de um transporte HTTP assíncrono para a camada REST. A
decisão foi adiada no `KrynCord-ARCHITECTURE.md` §7 até que um protótipo
validasse a escolha.

Critérios: suporte a `asyncio`, streaming, uploads multipart, timeouts
configuráveis, pool de conexões, suporte a Windows, facilidade de mock em
teste e saúde de manutenção.

## Decisão

Usar **httpx** (`>=0.28.1,<1`).

## Consequências

- `httpx.AsyncClient` é mockável injetando um transporte
  `httpx.BaseTransport`, o que permite testar rate limits e buckets sem
  rede — exatamente o que `tests/unit/http/` precisa.
- HTTP/2 vem habilitável sem trocar de biblioteca.
- Uma dependência a menos do que usar aiohttp para HTTP *e* WebSocket.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `aiohttp` | Mais rápido em throughput bruto, mas a API é mais verbosa e isolar o transporte em teste é mais trabalhoso. Ganho de performance irrelevante: o Discord limita a ~50 req/s por bucket. |
| `urllib3` + `asyncio` | Sem API assíncrona de primeira classe. |
| Implementar HTTP próprio | Fora do escopo — o projeto implementa o *protocolo Discord*, não o HTTP. |

## Risco conhecido

httpx não teve release estável nova desde 12/2024 (os `1.0.dev*` são
pré-release). É maduro e amplamente usado, mas vale acompanhar. A camada
`http/client.py` isola o transporte atrás de uma interface própria, então
trocar depois é pontual.
