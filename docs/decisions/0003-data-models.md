# 0003 — Modelos de dados: dataclasses

**Data:** 2026-10-11
**Status:** aceita

## Contexto

`User`, `Guild`, `Message`, `Channel`, `Member`, `Role`, `Attachment` e os
demais modelos precisam representar payloads da API com tipagem estática,
sem que a biblioteca obrigue o usuário a uma dependência de validação.

## Decisão

Usar **`dataclasses`** da biblioteca padrão, com parsing manual a partir do
payload cru.

## Consequências

- Zero dependências novas — coerente com o `docs/internals/architecture.md` §7.
- `mypy --strict` funciona sem plugin.
- O parsing fica em `models/base.py` com helpers próprios
  (`_get_str`, `_get_int`, `_get_optional`), centralizando a regra de
  "campo ausente ≠ campo com valor default".
- Modelos são **imutáveis por padrão** (`frozen=True`): um `Message` recebido
  do Gateway não muda de baixo dos pés. `state/event_updates.py` cria uma
  instância nova a partir de um payload parcial.

## Escopo inicial (Fase 3)

Só os modelos de que o caminho mínimo precisa:

`User`, `Message`, `Channel`, `Guild`, `Member`, `Role`, `Attachment`.

Os demais (~13 listados no `docs/internals/architecture.md` §6) entram quando um
endpoint concretamente precisar deles.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| `attrs` | Mais recursos que dataclasses, mas é dependência extra para ~o que as dataclasses fazem. |
| `pydantic` | Validação automática forte, mas pesado, e conflita com a regra de "sem dependência nova". |
| Payloads crus (`dict`) | Sem tipagem. Aceitável internamente, não na API pública. |

## Nota

Se um dia a validação automática virar necessária (ex.: para payloads de
usuário muito aninhados), a porta é `models/base.py` — trocar a implementação
do parsing sem mudar a API pública.
