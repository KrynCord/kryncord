# 0002 — Transporte WebSocket: websockets

**Data:** 2026-10-11
**Status:** aceita

## Contexto

O Gateway exige uma conexão WebSocket persistente com heartbeat, envio e
recebimento de payloads, controle de backpressure e reconexão. O transporte
precisa ser uma biblioteca *genérica* — a KrynCord implementa o protocolo
Discord, não o protocolo WebSocket.

## Decisão

Usar **websockets** (`>=17.2,<18`).

## Consequências

- websockets 17 exige Python ≥ 3.11, o mesmo floor da KrynCord — sem conflito.
- `ping_interval`/`ping_timeout` nativos cobrem parte da detecção de conexão
  zumbi; o heartbeat do Discord (opcode 1) continua sendo nosso, por cima.
- O servidor `websockets.serve` permite escrever um gateway falso nos testes
  de integração, sem rede real.
- Uma biblioteca para WebSocket, outra para HTTP — cada uma especializada.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `aiohttp` | Funcionaria e unificaria as duas dependências, mas aí o HTTP ficaria preso a ela. Manter HTTP e WS em bibliotecas separadas mantém `http/` e `gateway/` independentes por construção. |
| `websocket-client` | Síncrono. |
| `wsproto` | Mais baixo nível (frames), sem client assíncrono pronto. |

## Risco conhecido

Duas dependências de rede em vez de uma. Aceitável: `http/` e `gateway/` não
compartilham código além de `internal/`, então a superfície de acoplamento é
zero.
