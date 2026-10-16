# 0015 — Componentes: builders, validação e layout

## Contexto

A ideia 07 é o documento mais marcado da série — `⚠️`, `❌` e listas de
"pergunta em aberto" (A a X). Há três problemas concretos:

1. Três listas de módulos diferentes para `components/` (architecture §5,
   13 §6, 17)
2. `InteractionFlags` (V7) contra o que o Discord realmente define
3. V2 por padrão ou explícito, e como um `str` em `components=` se
   comporta

## Decisão

### Layout unificado de `components/`

```
components/
  __init__.py     exportações
  base.py         Component (pai), to_dict
  buttons.py      Button, create_link_button
  selects.py      String/User/Role/Mentionable/Channel select, create_*_select
  inputs.py       TextInput, Label, create_label
  modals.py       Modal, create_modal, create_modal_fields
  rows.py         ActionRow, create_row, create_components, create_components_rows
  displays.py     TextDisplay, Separator, Section, Container, MediaGallery, File, Thumbnail
  colors.py       color parsing, AccentColor
  validation.py   regras estruturais, ComponentError com caminho
```

`KrynCord-ARCHITECTURE.md` §5 é atualizado. O critério foi separar por
**tipo de componente** (o que muda na API) e isolar validação num módulo
só — porque a validação é a parte que precisa de caminho na mensagem.

`builders.py`, `containers.py` e `text_inputs.py` (architecture) foram
absorvidos: `builders.py` é largo demais para um módulo com dez
componentes, e `text_inputs.py` separado de `inputs.py` dividiria o
módulo de Label, que sempre vai junto.

### Builders são `@dataclass(frozen=True, slots=True)`

Idêntico aos models (`0003`) e ao `CachePolicy`. Um builder não muda
depois de construído — e a imutabilidade já é o contrato de toda a
biblioteca.

### Validação em duas camadas, cada uma no seu lugar

| Camada | Onde | O quê |
|---|---|---|
| Local | `__post_init__` do componente | limites de string, estilo × campos, `custom_id` em Button |
| Estrutural | `create_row` / `create_components` | ≤5 por row, não misturar com container, `str` só em V2 |

Validar no `to_dict()` seria tarde: o erro aparece na hora de responder,
não na hora de montar.

### Flag: `MessageFlags`, não `InteractionFlags`

A flag `IS_COMPONENTS_V2` é uma flag de **mensagem** — vai no payload da
mensagem, não num conceito "de interação". `EPHEMERAL` também é flag de
mensagem. O Discord não define `InteractionFlags`.

`MessageFlags` vive em `kryncord/enums.py`, junto de `GatewayOpcode` e
`CloseCode` — é um tipo que cruza camadas (builder → payload → teste).

### V2 não é o padrão

- `v2=False` é o comportamento, e as duas gerações são explícitas
- `v2=True` existe como atalho nos métodos de resposta, e seta
  `MessageFlags.IS_COMPONENTS_V2`
- **Auto-seleção por presença de `Container` é rejeitada**: mudar o
  payload conforme o que foi passado é comportamento invisível, e a
  surpresa aparece como "funcionou no meu teste e não no servidor"

`create_components` valida estrutura; a flag é de quem monta a mensagem.

### Um `str` dentro de `components=`

Normalização de `create_components`:

| Entrada | Saída |
|---|---|
| `str` | `TextDisplay` (só V2) |
| select | dentro de uma `ActionRow` nova |
| `None` / `False` | filtrado |
| `True` / `int` / objeto desconhecido | `ComponentError` com caminho |

`str` em V1 → `ComponentError` apontando que V1 não aceita texto em row.
Não é silencioso: o `str` no V1 é quase sempre um `content` que saiu do
lugar errado.

### Erros: `ComponentError` herda de `KrynCordError`

Não de `DefinitionError` — montar componente não é definir comando. A
mensagem carrega caminho `rows[2].components[3]`.

### Resposta a A–B (API)

- **A** `dataclass(frozen=True, slots=True)`, não classe fluent
- **B** Button sem `custom_id` e sem `url` → `ComponentError`; sem
  auto-geração
- **B2** Button sem `custom_id` → erro; `create_link_button` é a rota do
  URL
- **B3** `custom_id` ausente em Button → `ComponentError` (não default)
- **B6** sem auto-`/` no `custom_id`
- **B1** (fluent builder com `.label()`, `.style()`) → **rejeitado**:
  uma segunda forma de construir o mesmo objeto

### Resposta a E (Embed)

Embed é legado V1. Decisões:

- `source` é o nome do parâmetro (não `url`, que colide com link)
- `extends` **não** existe — `**kwargs` cobre
- `description` aceita `str | Sequence[str]`, junta com `\n`
- `Random` vira `random_color()`, função pura
- campo vazio usa `\u200b` (o Discord descarta string vazia)
- Embed auto-valida limites no construtor, como os demais
- `as_array` **não** existe: o Discord aceita objeto único, e a ideia
  dizia que `array` é "um só item sem delimitador" — não é um formato

### Resposta a L e M (inputs)

- `create_label(text=..., component=...)` aceita as três formas: keyword,
  posicional text, e `create_label("Texto", text_input)`
- `ModalFields` guarda o tipo esperado; `fields.to_dict()`, não
  `modal_fields_to_record`
- Acesso por atributo (`fields.name`) → **rejeitado**: é dict, use
  `fields["name"]` — atributo mágico sobre dict não é Python
- `TextInputStyle` em `enums.py`
- `create_text_input` **não** é alias de `TextInput`: um nome só
- `Checkbox` → `bool`
- `Label` rejeita `TextDisplay` (só `TextInput`/Select)
- **M1** `ActionRow` + `TextInput` legado → só via `raw`; a mistura não
  tem forma segura
- **M4** `send_modal` em `ctx` **e** em `interaction` — `ctx` delega
- **M5** modal V2 header: `TextDisplay` como primeiro componente
- **X4** `migrate_embed` → não existe na 1.0 (não há conversor)
- **X5** `content` + V2 → permitido; content funciona nas duas gerações

## Consequências

- A architecture precisa ser editada na §5 (módulos) e no enum
- `ComponentError` fica no `errors.py`, com os demais
- Os builders são ~15 dataclasses; todos passam pelo mesmo `to_dict`

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| V2 por padrão | Quebra os 100% de bots existentes que passam componentes V1 |
| Auto-flag por `Container` | Payload muda invisivelmente; surpresa só em produção |
| `InteractionFlags` | O Discord não define esse enum; a flag é de mensagem |
| Fluent builder | Segunda forma de construir o mesmo objeto, e a primeira já é constructor |
| `migrate_embed` na 1.0 | Conversor V1→V2 precisa de regras de layout que ninguém escreveu |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 17 Crítico | A auto-flag parecia "ajuda" e na prática é o bug clássico de funcionar no teste e falhar no servidor |
| 06 Arquitetura | Módulos por tipo de componente, validação isolada — porque o erro precisa de caminho |
| 11 Idiomático | `dataclass(frozen=True, slots=True)` é o contrato da biblioteca inteira; exceptions de formato |
| 19 Analista | Separação clara entre o que é local (construtor) e o que é estrutural (row) — regra aplicável a todo o resto |
| 04 RAM | slots em 15 dataclasses sem slots custaria ~50% a mais de memória por instância |
| 08 Segurança | `ComponentError` com caminho é o que impede o usuário perseguir linha errada |
| 01 Simplicidade | `fields["name"]` em vez de atributo mágico: um comportamento, não dois |

**Veredito do juiz: APROVADO COM AJUSTES.** O Juiz pediu que
`v2=True` fosse atalho de **método de resposta**, não de builder —
assim o builder continua puro e a flag fica onde a mensagem é montada.
Incorporado.

**Divergência preservada:** o Participante 20 (Visionário) queria
`migrate_embed` desde já, argumentando que a migração V1→V2 vai ser o
problema de todo mundo. Não prevaleceu por escopo: 1.0 entrega o que as
ideias especificam, e um conversor sem regras de layout testadas é
pior que não ter.

**Confiança: 86%.**
