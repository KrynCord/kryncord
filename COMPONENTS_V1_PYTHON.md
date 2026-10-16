# Components V1 (Legacy) — Embeds, Botões e Selects

Documentação das **regras de negócio do sistema clássico** (sem flag `IsComponentsV2`) e como a API fica na **sua lib Python**.

O sistema V1 continua válido. É o modelo:

```
Mensagem
├── content?          (texto)
├── embeds?           (até 10 embeds)
└── components?       (até 5 Action Rows)
    └── ActionRow
        ├── até 5 Buttons
        └── OU 1 Select Menu
```

---

## Sumário

1. [Regras de negócio V1](#1-regras-de-negócio-v1)
2. [Embed](#2-embed)
3. [Action Row](#3-action-row)
4. [Button](#4-button)
5. [Select Menus](#5-select-menus)
6. [API Python — sua lib](#6-api-python--sua-lib)
7. [Exemplos completos](#7-exemplos-completos)
8. [V1 vs V2 (quando usar cada um)](#8-v1-vs-v2-quando-usar-cada-um)

---

## 1. Regras de negócio V1

### O que pode ir na mensagem

| Campo | Limite | Observação |
|-------|--------|------------|
| `content` | 2000 caracteres | Texto livre, markdown |
| `embeds` | **10** por mensagem | Ver limites de embed abaixo |
| `components` | **5** Action Rows | Top-level apenas ActionRow |
| Attachments | Sim | Aparecem normalmente |
| Stickers / Poll | Sim | Permitidos |

**Não precisa** de flag especial. Sem `IsComponentsV2`.

### Action Row — regras

| Regra | Valor |
|-------|--------|
| Máximo de rows por mensagem | **5** |
| Por row: botões | **1 a 5** botões |
| Por row: select | **exatamente 1** select (ocupa a row inteira) |
| Misturar botão + select na mesma row | **Não** |

### Button — regras

| Campo | Limite / regra |
|-------|----------------|
| `custom_id` | Obrigatório (exceto Link e Premium), máx. **100** chars |
| `label` | Máx. **80** chars (ou emoji sozinho) |
| `url` | Só em style Link; máx. **512** chars |
| `emoji` | Opcional |
| `disabled` | bool |
| Styles | Primary, Secondary, Success, Danger, Link, Premium |

- Link button: **tem** `url`, **não tem** `custom_id`, **não dispara** interaction.
- Premium button: tem `sku_id`, não tem custom_id/label/url.
- Demais: precisam de `custom_id`.

### Select Menu — regras

| Tipo | Type ID | Opções |
|------|---------|--------|
| String Select | 3 | 1–25 options definidas por você |
| User Select | 5 | Discord fornece usuários |
| Role Select | 6 | Discord fornece cargos |
| Mentionable Select | 7 | Users + roles |
| Channel Select | 8 | Canais (filtráveis por tipo) |

| Campo | Limite |
|-------|--------|
| `custom_id` | Máx. **100** |
| `placeholder` | Máx. **150** |
| `min_values` | 0–25 |
| `max_values` | 1–25 |
| Option `label` / `value` / `description` | Máx. **100** cada |
| Options (String Select) | **1–25** |

- **Um select por Action Row.**
- Multi-select: use `min_values` e `max_values`.

### Embed — limites

| Campo | Limite |
|-------|--------|
| Embeds por mensagem | **10** |
| Title | **256** |
| Description | **4096** |
| Fields | **25** |
| Field name | **256** |
| Field value | **1024** |
| Footer text | **2048** |
| Author name | **256** |
| Total de caracteres (soma de todos os textos do embed) | **6000** |
| Image / thumbnail / author icon / footer icon | URL válida |

---

## 2. Embed

### Estrutura mental

```
Embed
├── title
├── description
├── url                    (título vira link)
├── color / colour
├── timestamp
├── footer { text, icon_url }
├── image { url }
├── thumbnail { url }
├── author { name, url, icon_url }
└── fields[] { name, value, inline }
```

### Facilitador sugerido: `createEmbed`

Inspirado no magicyan, mas completo para a sua lib.

**Opções aceitas:**

| Opção | Tipo | Descrição |
|-------|------|-----------|
| `title` | str | Título |
| `description` | str \| list[str] | Texto; lista vira linhas com `\n` |
| `url` | str | Link no título |
| `color` / `colour` | str \| int \| Color | `"Blue"`, `"Random"`, `"#5865F2"`, `0x5865F2` |
| `timestamp` | bool \| datetime | `True` = agora |
| `footer` | str \| dict | Só texto ou `{ text, icon_url }` |
| `image` | str \| dict \| Attachment | URL, `{ url }`, ou attachment → `attachment://...` |
| `thumbnail` | str \| dict \| Attachment | Idem |
| `author` | str \| dict | Nome ou `{ name, url, icon_url }` |
| `fields` | list[dict] | `[{ name, value, inline? }, ...]` |
| `from` | Message / Interaction | Copia embed existente |
| `fromIndex` | int | Qual embed pegar (default 0) |
| `extends` | Embed / dict | Base para herdar |
| `array` | bool | Se `True`, retorna lista |

---

## 3. Action Row

Container obrigatório para botões e selects no V1.

```
ActionRow
└── components: Button[] (1–5)  |  Select (1)
```

Facilitador: **`createRow(*components)`**

- Aceita botões e/ou um select.
- Filtra `None` / `False`.
- Não mistura botões + select (regra da API).

---

## 4. Button

### Styles

| Nome | Uso típico |
|------|------------|
| `Primary` | Ação principal (azul) |
| `Secondary` | Secundário (cinza) |
| `Success` | Confirmar (verde) |
| `Danger` | Deletar / cancelar destrutivo (vermelho) |
| `Link` | Abre URL (não gera interaction) |
| `Premium` | SKU (loja) |

### Facilitadores

- **`ButtonBuilder`** — builder fluent da lib
- **`createLinkButton(label=..., url=..., emoji=...)`** — atalho para Link

---

## 5. Select Menus

### String Select

Você define as opções:

```python
createStringSelect(
    customId="color",
    placeholder="Escolha uma cor",
    options=[
        {"label": "Vermelho", "value": "red", "emoji": "🔴"},
        {"label": "Azul", "value": "blue", "description": "Cor padrão"},
    ],
    minValues=1,
    maxValues=1,
)
```

### User / Role / Mentionable / Channel Select

Discord preenche as opções. Você só configura:

```python
createUserSelect(customId="users", placeholder="Selecione usuários", minValues=1, maxValues=5)
createRoleSelect(customId="roles", placeholder="Selecione cargos")
createChannelSelect(customId="channel", channelTypes=[ChannelType.Text])
```

Todos precisam ir dentro de **`createRow(...)`**.

---

## 6. API Python — sua lib

Tudo importado de `sua_lib` (lib completa).

```python
from sua_lib import (
    # Embed
    createEmbed,
    # Rows / botões / selects
    createRow,
    createLinkButton,
    createStringSelect,
    createUserSelect,
    createRoleSelect,
    createMentionableSelect,
    createChannelSelect,
    ButtonBuilder,
    ButtonStyle,
    # Opcional: helpers de texto
    brBuilder,  # junta linhas com \n
)
```

### Convenções

| Comportamento | Regra |
|---------------|--------|
| `None` / `False` em rows | Filtrados |
| `description` como lista | Vira texto com quebras de linha |
| `color="Random"` | Cor aleatória |
| `color="Blue"` / `"#5865F2"` / `0x5865F2` | Aceitos |
| `image` / `thumbnail` com Attachment | Converte para `attachment://nome` |
| Botões e selects | Sempre dentro de `createRow` ao montar a mensagem |
| Mensagem V1 | `content` + `embeds` + `components` juntos, **sem** flag V2 |

---

## 7. Exemplos completos

### 7.1 Só embed

```python
from sua_lib import createEmbed

embed = createEmbed(
    title="Welcome to the Server!",
    description=[
        "Thanks for joining us!",
        "",
        "Please read the rules in #rules",
    ],
    color="Green",
    timestamp=True,
    footer="Server Team",
    thumbnail="https://cdn.discordapp.com/icons/....png",
)

await interaction.response.send_message(embeds=[embed])
```

### 7.2 Embed completo com fields

```python
embed = createEmbed(
    title="Perfil",
    description="Informações do usuário",
    color="#5865F2",
    url="https://exemplo.com",
    author={"name": "Bot", "icon_url": "https://exemplo.com/bot.png"},
    thumbnail="https://exemplo.com/avatar.png",
    image="https://exemplo.com/banner.png",
    fields=[
        {"name": "Nível", "value": "42", "inline": True},
        {"name": "XP", "value": "1200", "inline": True},
        {"name": "Bio", "value": "Desenvolvedor", "inline": False},
    ],
    footer={"text": "ID: 123", "icon_url": "https://exemplo.com/icon.png"},
    timestamp=True,
)

await interaction.response.send_message(embeds=[embed])
```

### 7.3 Embed + botões

```python
from sua_lib import (
    createEmbed,
    createRow,
    createLinkButton,
    ButtonBuilder,
    ButtonStyle,
)

embed = createEmbed(
    title="Confirmar ação",
    description="Deseja continuar?",
    color="Orange",
)

row = createRow(
    ButtonBuilder().setCustomId("confirm").setLabel("Confirmar").setStyle(ButtonStyle.Success),
    ButtonBuilder().setCustomId("cancel").setLabel("Cancelar").setStyle(ButtonStyle.Danger),
    createLinkButton(label="Docs", url="https://docs.exemplo.com"),
)

await interaction.response.send_message(
    embeds=[embed],
    components=[row],
)
```

### 7.4 Várias rows de botões (máx. 5 botões por row)

```python
row1 = createRow(
    ButtonBuilder().setCustomId("a").setLabel("A").setStyle(ButtonStyle.Primary),
    ButtonBuilder().setCustomId("b").setLabel("B").setStyle(ButtonStyle.Primary),
    ButtonBuilder().setCustomId("c").setLabel("C").setStyle(ButtonStyle.Primary),
    ButtonBuilder().setCustomId("d").setLabel("D").setStyle(ButtonStyle.Primary),
    ButtonBuilder().setCustomId("e").setLabel("E").setStyle(ButtonStyle.Primary),
)

row2 = createRow(
    ButtonBuilder().setCustomId("f").setLabel("F").setStyle(ButtonStyle.Secondary),
)

await interaction.response.send_message(
    content="Escolha uma opção:",
    components=[row1, row2],
)
```

### 7.5 String Select

```python
from sua_lib import createRow, createStringSelect

select = createStringSelect(
    customId="starter",
    placeholder="Escolha seu starter",
    options=[
        {"label": "Bulbasaur", "value": "bulbasaur", "emoji": "🌱"},
        {"label": "Charmander", "value": "charmander", "emoji": "🔥"},
        {"label": "Squirtle", "value": "squirtle", "emoji": "💧"},
    ],
)

row = createRow(select)

await interaction.response.send_message(
    content="Escolha!",
    components=[row],
)
```

### 7.6 User Select (multi)

```python
row = createRow(
    createUserSelect(
        customId="members",
        placeholder="Selecione até 5 membros",
        minValues=1,
        maxValues=5,
    )
)

await interaction.response.send_message(
    content="Quem participa?",
    components=[row],
)
```

### 7.7 Embed + select + botões (mensagem completa V1)

```python
from sua_lib import (
    createEmbed,
    createRow,
    createStringSelect,
    createLinkButton,
    ButtonBuilder,
    ButtonStyle,
)

embed = createEmbed(
    title="Painel",
    description="Configure o servidor",
    color="Blurple",
    thumbnail=guild.icon.url if guild.icon else None,
)

row_select = createRow(
    createStringSelect(
        customId="setting",
        placeholder="Escolha uma configuração",
        options=[
            {"label": "Prefixo", "value": "prefix"},
            {"label": "Idioma", "value": "lang"},
            {"label": "Logs", "value": "logs"},
        ],
    )
)

row_buttons = createRow(
    ButtonBuilder().setCustomId("save").setLabel("Salvar").setStyle(ButtonStyle.Success),
    ButtonBuilder().setCustomId("reset").setLabel("Resetar").setStyle(ButtonStyle.Danger),
    createLinkButton(label="Ajuda", url="https://docs.exemplo.com"),
)

await interaction.response.send_message(
    embeds=[embed],
    components=[row_select, row_buttons],
)
```

### 7.8 Image via attachment

```python
# Sua lib aceita attachment e normaliza para attachment://
embed = createEmbed(
    title="Resultado",
    image=attachment,  # Attachment / bytes com nome → attachment://file.png
)

await interaction.response.send_message(
    embeds=[embed],
    files=[attachment],
)
```

---

## 8. V1 vs V2 — quando usar cada um

| Situação | Use |
|----------|-----|
| Texto + embed clássico + botões/selects | **V1** (`content` / `embeds` / `components`) |
| Layout rico (seções, galeria, container, texto estruturado) | **V2** (`flags=IsComponentsV2`, sem embeds) |
| Modal (formulário) | Sistema de modal (Label + inputs) — independente de V1/V2 de mensagem |
| Compatibilidade máxima / bots antigos | **V1** |
| UI moderna tipo “card” | **V2** (`createContainer`, etc.) |

### Resumo visual

```
V1 (legacy)
  content + embeds[0..10] + components[ActionRow × ≤5]
  ActionRow → 5 buttons  |  1 select

V2 (IsComponentsV2)
  components[] só (TextDisplay, Container, Section, MediaGallery, Separator, ActionRow…)
  SEM content, SEM embeds
```

---

## Checklist de implementação (sua lib — V1)

- [ ] `createEmbed` com title, description (str/list), color, timestamp, footer, author, image, thumbnail, fields
- [ ] Normalização de `image`/`thumbnail`: URL, dict, Attachment → `attachment://`
- [ ] `color`: nome, hex, int, `"Random"`
- [ ] `createRow(*items)` filtrando None/False
- [ ] `createLinkButton(label, url, emoji?)`
- [ ] `ButtonBuilder` fluent (setCustomId, setLabel, setStyle, setEmoji, setDisabled)
- [ ] `createStringSelect` / `createUserSelect` / `createRoleSelect` / `createMentionableSelect` / `createChannelSelect`
- [ ] Validação ou docs: máx. 5 rows, 5 botões/row, 1 select/row
- [ ] Envio V1 **sem** `MessageFlags.IsComponentsV2`
- [ ] Tudo exportado de `sua_lib` (sem importar builders do discord para montar UI)

---

## Referência rápida de types (V1)

| Type | Nome |
|------|------|
| 1 | Action Row |
| 2 | Button |
| 3 | String Select |
| 5 | User Select |
| 6 | Role Select |
| 7 | Mentionable Select |
| 8 | Channel Select |

(Text Input type 4 é de **modal**, não de mensagem V1.)
