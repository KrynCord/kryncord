# 0024 — Bloco de componentes: a lacuna da 0015 e a serialização ponta a ponta

## Contexto

Pedido: **`components/` completo, seguindo o estilo dos `.md`, tão
completo quanto o discord.js.**

O inventário foi feito no pacote de builders do repo de referência
(`base/discord.js/packages/builders/src/`), arquivo por arquivo. Contra
as ideias 13–18 e a decisão `0015`, ele mostrou:

1. **Um furo no layout da `0015`.** A ideia 15 §3 lista os filhos
   aceitos por `Label`: `TextInput`, os 5 selects, `FileUpload` (19),
   `RadioGroup` (21), `CheckboxGroup` (22), `Checkbox` (23). O layout
   unificado da `0015` — que absorveu `label.py` e `text_inputs.py`
   em `inputs.py` — **não tem casa para nenhum dos quatro últimos**.
   A `0015` focou em V2 e nas decisões B/E/L/M; o inventário de
   modal dela parou em `TextInput`.
2. **Os componentes não chegavam ao HTTP.** `api/interactions.py` e
   `api/messages.py` passam `kwargs` crus ao `json=`. Um
   `components=[create_row(...)]` mandaria dataclasses ao httpx —
   o caminho inteiro existia só no papel.

### Números de tipo

`ComponentType` no `enums.py` cobre 1–8 (a Fase 4 usou). Os V2 e os de
modal que faltam: `Section` 9, `TextDisplay` 10, `Thumbnail` 11,
`MediaGallery` 12, `File` 13, `Separator` 14, `Container` 17, `Label`
18, `FileUpload` 19, `RadioGroup` 21, `CheckboxGroup` 22, `Checkbox`
23 — fonte: ideias 13 §4 e 15 §3. O enum de `discord-api-types` não
está vendado no repo; as ideias são a especificação do usuário e os
números conferem com a API pública do Discord.

## Decisão

### C1 — `uploads.py` e `choices.py` existem; `inputs.py` fica `Label` + `TextInput`

O critério da `0015` para absorver foi coesão: *"`text_inputs.py`
separado de `inputs.py` dividiria o módulo de Label, que sempre vai
junto"*. `Label` + `TextInput` é um par (1 rótulo : 1 campo, sempre).
`FileUpload` não é input de texto, e `RadioGroup`/`CheckboxGroup`/
`Checkbox` são componentes de **escolha** — a mesma coesão que pôs os
5 selects em `selects.py` manda agrupá-los:

```
components/
  __init__.py     exportações
  base.py         Component (pai), era, to_dict, walk
  buttons.py      Button, create_link_button
  selects.py      5 selects, create_*_select, SelectOption
  inputs.py       TextInput, Label, create_label, create_text_input
  uploads.py      FileUpload, create_file_upload
  choices.py      RadioGroup, CheckboxGroup, Checkbox
  modals.py       Modal, create_modal, create_modal_fields
  rows.py         ActionRow, create_row, create_components, create_components_rows
  displays.py     TextDisplay, Separator, Section, Container, MediaGallery, File, Thumbnail, create_*
  colors.py       AccentColor, parse_color, random_color
  validation.py   regras estruturais, ComponentError com caminho
```

Doze arquivos — os dez da `0015` mais os dois da ideia 15 §7 que o
inventário dela não alcançou.

### C2 — `era` é `ClassVar` no componente (X2 confirmado)

```python
class Button(Component):
    era: ClassVar[Era] = "both"  # ActionRow, Button, selects
```

`Embed` é `"v1"`, `Container` é `"v2"`, `ActionRow`/`Button`/selects
são `"both"`. Um lugar só decide, e a tabela da ideia 18 §4 vira teste
de tabela. `ClassVar` — a época é da **classe**, não da instância, e
dataclass `frozen` não o confunde com campo.

### C3 — A serialização chega ao HTTP; `v2=True` é atalho da resposta

`_message_data` (api/interactions.py) e `_body` (api/messages.py)
ganham uma normalização **compartilhada** antes do `json=`:

| Entrada | Saída |
|---|---|
| `Component` | `to_dict()` |
| lista de `Component` | cada um serializado |
| `Embed` / lista de `Embed` | `to_dict()` de cada |
| `flags=[MessageFlags.X]` | inteiro OU-ed |
| `flags=MessageFlags.X` / `int` | passado |
| `v2=True` | pop + `IS_COMPONENTS_V2` no inteiro de flags |

A normalização é **aditiva**: quem já mandava dict cru continua
funcionando (o teste existente de `_body` não muda). `v2=True` mora na
camada de resposta, como a `0015` determinou ("atalho nos métodos de
resposta, não de builder") — o ponto de convergência dos métodos é
exatamente `_message_data`.

### C4 — `ReplyOptions` em `builders/messages.py`

É o único lugar que conhece os dois sistemas (ideia 18 §4):

| Combinação | Resultado |
|---|---|
| `content`/`embeds` + `components` V2 + flag | `ComponentError` |
| `components` V2 sem flag | `ComponentError` |
| flag sem `components` V2 | `ComponentError` — flag órfã |
| V1 completo (`content`/`embeds`/rows, sem flag) | válido |
| `v2=True` com `content`/`embeds` | `ComponentError` — mesmo caso, outro sinal |

`to_payload()` devolve o `dict` pronto para `**` espalhar na resposta.

### C5 — Declinado: builders de `Poll`, `AllowedMentions`, `Attachment`, `MessageReference`

O discord.js os tem; as ideias **nunca os especificam** — poll só
aparece como "V1 permite" (16 §1, 18 §2), e a leitura dessas
estruturas já mora em `models/`. Builder sem especificação do usuário
é adivinhação de API pública — a parte cara de mudar. Registrado como
lacuna conhecida; entra quando houver ideia escrevendo o que ele deve
fazer.

### C6 — Um `Button` só, contra três classes do discord.js

discord.js divide `CustomIdButton`/`LinkButton`/`PremiumButton`. A
`0015` já fechou o contrário (uma classe, validação por style × campo,
B/B2/B3), e o levantamento confirmou que a divisão existe lá para
resolver tipagem de overload TS — problema que Python não tem.
Confirmado; `create_link_button` segue como o único atalho.

### C7 — `Separator` em três formas, `SeparatorSize` no `displays.py`

`Separator.default()` (divisor, spacing pequeno), `Separator.large()`
(divisor, spacing grande), `Separator.small()` (espaço, sem divisor —
"espaço pequeno" da 13 §5.1 é spacing sem linha). `SeparatorSize`
(`SMALL=1`, `LARGE=2`) é enum de builder → mora em `displays.py`,
junto do componente, pela mesma régua do `TextInputStyle` (L3).

## Consequências

- `enums.py` cresce `ComponentType` (9–14, 17–19, 21–23), `MessageFlags`
  (V7), `ButtonStyle` e `ChannelType` (B4). Nenhum valor existente
  muda — só adição.
- `_message_data` e `_body` importam `components/` — dependência
  nova entre api/ e components/, e ela é o ponto: serializar é
  responsabilidade do builder, e a camada HTTP só normaliza.
- `ModalFields.get_files` (15 §5) precisa do tipo esperado por
  `custom_id`, que o payload do submit não traz — fica como restrição
  registrada, adiada até o bloco de fluxo de modal ter um teste de
  ponta a ponta real.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Absorver uploads/choices em `inputs.py` | Um arquivo com 8 classes de 4 naturezas diferentes; a coesão que criou `selects.py` mandaria criar `choices.py` amanhã |
| Serialização só no `ReplyOptions` | Quem usa `ctx.reply(components=...)` direto mandaria dataclass ao httpx — o caminho comum seria o quebrado |
| `Poll`/`AllowedMentions` builders "para completar" | API pública sem especificação do usuário é adivinhação; a parte cara de mudar depois |
| Três classes de Button | Existe para resolver overload TS; Python valida por style × campo na `__post_init__` |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 19 Analista | O furo da 0015 é factual: ideia 15 §3 lista 4 filhos de Label que o layout não aloja — a decisão é corrigir o layout, não ignorar os filhos |
| 06 Arquitetura | `uploads.py`/`choices.py` seguem o critério real da 0015 (coesão por tipo), não a letra do arquivo dela |
| 17 Crítico | `components=[row]` chegando cru ao httpx era o achado mais caro: o módulo inteiro era testável e inútil ao mesmo tempo |
| 11 Idiomático | `ClassVar` para `era` — época é da classe; campo de instância mentiria sobre o que é fixo |
| 09 Testes | A tabela da 18 §4 vira teste de tabela, e `era` é o que torna isso possível sem lista de nomes espalhada |
| 18 Pragmático | `_message_data` normalizar aditivamente: quem já mandava dict cru não quebra, e o teste existente fica de graça |
| 08 Segurança | Declinar `Poll` por falta de especificação é o mesmo critério do `migrate_embed` na 0015 — escopo é o que a ideia escreve |
| 01 Simplicidade | Um `Button` com validação por style contra três classes: menos superfície, a mesma garantia |

**Veredito do juiz: APROVADO COM AJUSTES.** Os ajustes: (a) registrar
que `ComponentType` estende sem renomear valores existentes (o
`ResponderType.de_interacao` da Fase 4 depende de `ComponentType(2..8).name`),
(b) a normalização de `_message_data` precisa de teste de
retrocompatibilidade explícito — dict cru entra, dict cru sai.

**Divergência preservada:** o Participante 20 (Visionário) reiterou o
`migrate_embed` agora que os dois sistemas existem em código. Não
prevaleceu pelo mesmo motivo da 0015: o mapeamento visual (footer →
`TextDisplay`?) continua sendo decisão de layout que ninguém
escreveu.

**Confiança: 88%.**

## Correção registrada na implementação

Dois bugs saíram dos testes, e ambos são da família que a decisão
previu sem conseguir fechar sozinha:

1. **`Label` sem `era`.** A C2 dizia que todo componente declara época
   — e a implementação esqueceu a declaração no próprio `Label`, que
   herdaria `"both"` do pai e passaria como componente de mensagem. É
   exatamente o caso que o `"modal"` foi criado para impedir, achado
   pelo teste `TestEra` antes de existir qualquer dispatch real.
   `Label.era = "modal"`, e o teste ficou de garde.
2. **`_message_data` validava `content` depois de ele existir.** O
   `content` era adicionado ao corpo **após** a `normalizar_mensagem`
   rodar — a tabela V1 × V2 nunca o via, e `content` + flag V2 passava
   (o caso "o Discord ignora em silêncio" que a tabela existe para
   recusar). Corrigido nos dois pontos de convergência
   (`api/interactions._message_data` e `api/messages._body`): o
   `content` entra antes da normalização.

A confiança revisada: **86%** — o parágrafo acima mostra que a
validação de fronteira só é real quando o teste de fronteira existe.
