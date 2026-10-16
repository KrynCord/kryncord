# 0005 — Reconexão do Gateway: classificação de close code e descarte de sessão

**Data:** 2026-10-11
**Status:** aceita

## Contexto

A Fase 2 precisa responder, para cada queda de conexão, uma de três
perguntas: a sessão ainda vale (`RESUME`), morreu (`IDENTIFY`), ou não
adianta reconectar (`FATAL`). O `KrynCord-ARCHITECTURE.md` descreve o
fluxo, mas não fixa a tabela — e a tabela é o único lugar onde um erro
se manifesta como "o bot volta em 5 segundos" ou "o bot volta em 30
minutos, reconstruindo tudo".

Havia também uma segunda resposta à mesma pergunta em `enums.py`
(`CloseCode.should_resume`), binária e divergente: ela dizia que o código
1000 retomava sessão, enquanto o `WebSocketShard.onClose` do discord.js
— e a observação de campo — diz que encerramento normal significa sessão
encerrada.

## Decisão

**1. Uma tabela, uma fonte.** A classificação mora em
`gateway/reconnect.classify_close`, que devolve `Recovery.RESUME`,
`Recovery.IDENTIFY` ou `Recovery.FATAL` — três respostas, não duas.
`CloseCode.should_resume` foi removido de `enums.py`: uma resposta binária
ali seria uma segunda, divergente, sobre o mesmo fato.

**2. A tabela, copiada do discord.js** (`WebSocketShard.onClose`):

| Código | Recuperação |
|---|---|
| 4004, 4010–4014 | **FATAL** |
| 1000, 4003, 4005, 4007, 4008 | IDENTIFY |
| 4000–4002, 4009, 4200 | RESUME |
| fora de tabela | RESUME; **IDENTIFY** se houve erro de rede |

**3. `IDENTIFY` descarta a sessão do store.** Quando a classificação é
`IDENTIFY`, `_run_once` chama `store.update(shard_id, None)` antes de
retornar. Sem isto, a próxima tentativa leria a `session_id` antiga e
mandaria `RESUME` para um close code que acabou de dizer "identify" —
pagando um round-trip até o `invalid_session` confirmar o que a tabela
já sabia.

**4. A decisão é registrada com o motivo.** `CloseDecision` carrega
`reason`, que vira a linha de log. Um bot que volta em 30 minutos sem
explicação no log é indistinguível de um que travou.

## Consequências

- Um close code novo que o Discord inventar cai em "fora de tabela" e
  tenta `RESUME` — o lado seguro. Com erro de rede antes, o lado seguro
  é `IDENTIFY`.
- `classify_close` é testado linha a linha. Mudar uma tabela é quebrar
  um teste, que é o comportamento desejado.
- O custo de errar é assimétrico: `RESUME` errado custa um round-trip e
  um `invalid_session`; `IDENTIFY` errado custa todos os eventos da
  queda e um `READY` extra. Por isso `FATAL` só é declarado de forma
  explícita — uma falsa positiva ali é um bot que desiste de viver.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Binário (`should_resume`) | Não dá para expressar "a sessão morreu mas reconecta" — que é o caso mais comum de todos (1000, 4008). |
| `RESUME` tentado sempre, `invalid_session` resolvendo | Round-trip a cada queda comum, e o `invalid_session` de resposta custa 1–5s de espera obrigatória. |
| Tabela em `config.py`, configurável | Nenhum usuário real precisa mudar uma tabela que vem do protocolo do Discord. Configurar seria uma forma de quebrar o próprio bot. |

## Referência

`base/discord.js/packages/ws/src/ws/WebSocketShard.ts`, função `onClose`
(linha 869), e o tratamento de `invalid_session` no mesmo arquivo.
