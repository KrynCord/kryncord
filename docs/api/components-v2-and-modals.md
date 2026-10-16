# Components V2 & Modals

Documentação dos facilitadores de **Components V2** e **Modals (Label)** inspirados em `@magicyan/discord`, e como a API fica na **sua lib Python**.

---

## Sumário

1. [Regras de negócio — Components V2](#1-regras-de-negócio--components-v2)
2. [Facilitadores Components V2 (magicyan)](#2-facilitadores-components-v2-magicyan)
3. [Facilitadores de Modal + Label (magicyan)](#3-facilitadores-de-modal--label-magicyan)
4. [API Python — sua lib](#4-api-python--sua-lib)
5. [Exemplos completos Python](#5-exemplos-completos-python)
6. [Referência rápida de tipos](#6-referência-rápida-de-tipos)

---

## 1. Regras de negócio — Components V2

### Flag obrigatória

Para enviar Components V2, a mensagem **deve** incluir a flag:

```ts
flags: MessageFlags.IsComponentsV2  // 1 << 15 = 32768
```

- Depois de enviada com essa flag, **não dá para remover**.
- Legacy (content + embeds + components antigos) continua funcionando **sem** a flag.

### O que é desabilitado com a flag

Quando `IsComponentsV2` está ativo:

| Campo | Status |
|-------|--------|
| `content` | **Não funciona** — use `TextDisplay` |
| `embeds` | **Não funciona** — use `Container` / `TextDisplay` / `Section` |
| `stickers` | **Desabilitado** |
| `poll` | **Desabilitado** |
| Attachments | **Não aparecem sozinhos** — precisam ser expostos via `MediaGallery`, `File` ou `Thumbnail` |

### Limites

| Limite | Valor |
|--------|-------|
| Total de components por mensagem | **40** (incluindo aninhados) |
| Caracteres totais em todos os `TextDisplay` | **4000** |
| TextDisplays dentro de uma `Section` | **3** |
| Imagens em uma `MediaGallery` | **10** |
| Botões em uma Action Row | **5** |
| Label de botão | **80** caracteres |
| URL de botão | **512** caracteres |
| URL de mídia | **2048** caracteres |
| Alt text de imagem | **1024** caracteres |
| Label (modal) | **45** caracteres |
| Description (modal Label) | **100** caracteres |

### Hierarquia de components

```
Mensagem (flags: IsComponentsV2)
├── TextDisplay          (type 10)  — texto markdown
├── Separator            (type 14)  — espaço / divisor
├── MediaGallery         (type 12)  — grade de mídia
├── File                 (type 13)  — arquivo anexado
├── Section              (type 9)   — texto + accessory (Thumbnail ou Button)
│   ├── TextDisplay ×1–3
│   └── accessory: Thumbnail | Button
├── ActionRow            (type 1)   — botões / selects
│   └── Button | Select
└── Container            (type 17)  — agrupador com accent color
    ├── TextDisplay
    ├── Separator
    ├── Section
    ├── MediaGallery
    ├── File
    └── ActionRow
```

### Regras de Section

- **Obrigatório** ter um `accessory` (Thumbnail **ou** Button).
- Máximo **3** TextDisplay dentro.
- Se não quiser accessory → use `TextDisplay` solto, não Section.

### Regras de Container

- Pode ter accent color (barra lateral, similar a embed).
- Pode ser marcado como spoiler.
- Filhos permitidos: TextDisplay, Separator, Section, MediaGallery, File, ActionRow.
- **Não** aninha Container dentro de Container.

### Regras de Modal (novo sistema)

| Regra | Detalhe |
|-------|---------|
| TextInput **deve** ficar dentro de **Label** (type 18) | ActionRow + TextInput está **deprecated** |
| Label tem `label` + `description` opcional | O `label` do TextInput em si está deprecated |
| Label filhos permitidos | TextInput, String/User/Role/Mentionable/Channel Select, FileUpload, RadioGroup, CheckboxGroup, Checkbox |
| Top-level no modal | Label, TextDisplay (e legados ActionRow ainda aceitos por compat) |
| File Upload | type 19 — só em modal, dentro de Label |

---

## 2. Facilitadores Components V2 (magicyan)

### Import

```ts
import {
  createComponents,
  createContainer,
  createTextDisplay,
  createSection,
  createSeparator,
  createMediaGallery,
  createFile,
  createRow,
  createLinkButton,
  Separator,
} from "@magicyan/discord";
import { ButtonBuilder, ButtonStyle, MessageFlags } from "discord.js";
```

### `createTextDisplay`

```ts
const text = createTextDisplay("# Título\nTexto com **markdown**");
```

### `createSeparator`

```ts
createSeparator(true, true);   // large + divider
Separator.Large;
Separator.Default;
Separator.Small;
```

### `createRow` / `createLinkButton`

```ts
const row = createRow(
  new ButtonBuilder()
    .setCustomId("ok")
    .setLabel("Ok")
    .setStyle(ButtonStyle.Success),
  createLinkButton({ label: "Site", url: "https://exemplo.com" })
);
```

### `createSection`

```ts
const section = createSection(
  createTextDisplay("**Status**\nTudo online"),
  createTextDisplay("Segunda linha"),
  // accessory
  new ButtonBuilder()
    .setCustomId("details")
    .setLabel("Detalhes")
    .setStyle(ButtonStyle.Primary)
);
```

### `createMediaGallery`

```ts
const gallery = createMediaGallery(
  "https://exemplo.com/1.png",
  "https://exemplo.com/2.png"
);
```

### `createFile`

```ts
const file = createFile("attachment://documento.pdf");
```

### `createContainer`

```ts
const container = createContainer(
  "Blue", // ou "#5865F2"
  createTextDisplay("# Título"),
  createTextDisplay("Corpo da mensagem"),
  Separator.Large,
  createRow(
    new ButtonBuilder()
      .setCustomId("confirm")
      .setLabel("Confirmar")
      .setStyle(ButtonStyle.Success)
  )
);
```

### `createComponents` (factory principal)

- Strings → `TextDisplay`
- Button / Select → envolvidos em `ActionRow`
- Attachment → `MediaGallery`
- `null` / `undefined` / `false` → filtrados (condicionais)

```ts
const components = createComponents(
  createContainer(
    "#5865F2",
    "# Bem-vindo",
    "Escolha uma opção:",
    Separator.Default,
    createSection(
      createTextDisplay("**Status**\nOnline"),
      new ButtonBuilder()
        .setCustomId("status")
        .setLabel("Detalhes")
        .setStyle(ButtonStyle.Primary)
    ),
    createMediaGallery("https://exemplo.com/banner.png"),
    createRow(
      createLinkButton({ label: "Docs", url: "https://docs.exemplo.com" }),
      new ButtonBuilder()
        .setCustomId("help")
        .setLabel("Ajuda")
        .setStyle(ButtonStyle.Secondary)
    ),
    False && createTextDisplay("não aparece"),
    null
  )
);

await interaction.reply({
  components,
  flags: MessageFlags.IsComponentsV2,
});
```

---

## 3. Facilitadores de Modal + Label (magicyan)

### Import

```ts
import {
  createModal,
  createModalFields,
  createLabel,
  createTextInput,
  createFileUpload,
  modalFieldsToRecord,
} from "@magicyan/discord";
import { ComponentType, TextInputStyle } from "discord.js";
```

### `createLabel` (LabelBuilder — type 18)

```ts
// Com description
createLabel("Nome", "Digite seu nome completo", {
  type: ComponentType.TextInput,
  customId: "name",
  style: TextInputStyle.Short,
  required: true,
});

// Sem description
createLabel("Idade", {
  type: ComponentType.TextInput,
  customId: "age",
  style: TextInputStyle.Short,
});

// Objeto
createLabel({
  label: "Username",
  description: "Seu nick no servidor",
  component: {
    type: ComponentType.TextInput,
    customId: "username",
    style: TextInputStyle.Short,
  },
});
```

### `createTextInput`

```ts
createTextInput({
  customId: "bio",
  style: TextInputStyle.Paragraph,
  maxLength: 500,
  placeholder: "Conte sobre você...",
});
```

> `createModalInput` está **deprecated** (usava ActionRow). Use `createLabel` + `createTextInput`.

### `createModalFields`

Aceita strings (→ TextDisplay), Labels, e filtra `null`/`false`.

```ts
const fields = createModalFields(
  "Preencha os dados abaixo:",
  createLabel("Nome", "Nome completo", {
    type: ComponentType.TextInput,
    customId: "name",
    style: TextInputStyle.Short,
    required: true,
  }),
  createLabel("Bio", "Opcional", {
    type: ComponentType.TextInput,
    customId: "bio",
    style: TextInputStyle.Paragraph,
    maxLength: 500,
  })
);
```

### `createModal`

```ts
const modal = createModal({
  customId: "registration",
  title: "Cadastro",
  components: createModalFields(
    "Bem-vindo! Complete o formulário:",
    createLabel("Nome", "Seu nome completo", {
      type: ComponentType.TextInput,
      customId: "name",
      style: TextInputStyle.Short,
      required: true,
    }),
    createLabel("Bio", {
      type: ComponentType.TextInput,
      customId: "bio",
      style: TextInputStyle.Paragraph,
      maxLength: 500,
    })
  ),
});

await interaction.showModal(modal);
```

### `modalFieldsToRecord` (submit)

```ts
function run(interaction: ModalSubmitInteraction) {
  const fields = modalFieldsToRecord(interaction.fields);
  // fields.name, fields.bio
}
```

### `createFileUpload` (type 19)

```ts
createLabel("Anexo", "Envie um arquivo", {
  type: ComponentType.FileUpload, // ou via createFileUpload
  customId: "upload",
  // minValues / maxValues conforme API
});
```

---

## 4. API Python — sua lib

A lib é **completa**: o usuário importa só dela. Estilo camelCase igual ao magicyan.

### Import único

```python
from sua_lib import (
    # Components V2
    createTextDisplay,
    createContainer,
    createComponents,
    createSection,
    createSeparator,
    createMediaGallery,
    createFile,
    createRow,
    createLinkButton,
    Separator,
    # Modal
    createModal,
    createModalFields,
    createLabel,
    createTextInput,
    createFileUpload,
    modalFieldsToRecord,
    # Builders / enums
    ButtonBuilder,
    ButtonStyle,
    TextInputStyle,
    ComponentType,
    MessageFlags,
)
```

### Convenções da API Python

| Comportamento | Regra |
|---------------|--------|
| Strings em `createComponents` / `createContainer` / `createModalFields` | Viram `TextDisplay` |
| `None` / `False` | Filtrados (permite condicionais) |
| Button / Select sozinhos | Auto-envolvidos em ActionRow |
| `createContainer(cor, *comps)` | Forma principal de layout V2 |
| `createLabel(label, description?, component)` | Forma principal de campo de modal |
| Tudo vem de `sua_lib` | Zero import de `discord` para montar UI |

---

## 5. Exemplos completos Python

### 5.1 Components V2 — mensagem completa

```python
from sua_lib import (
    createComponents,
    createContainer,
    createTextDisplay,
    createSection,
    createMediaGallery,
    createRow,
    createLinkButton,
    Separator,
    ButtonBuilder,
    ButtonStyle,
    MessageFlags,
)

components = createComponents(
    createContainer(
        "Blue",
        createTextDisplay("# Bem-vindo ao Bot"),
        createTextDisplay("Aqui você encontra tudo que precisa."),
        Separator.Large,
        createSection(
            createTextDisplay("**Status do servidor**\nOnline e estável"),
            accessory=ButtonBuilder()
            .setCustomId("status")
            .setLabel("Ver detalhes")
            .setStyle(ButtonStyle.Primary),
        ),
        createMediaGallery(
            "https://exemplo.com/1.png",
            "https://exemplo.com/2.png",
        ),
        createRow(
            createLinkButton(label="Documentação", url="https://docs.exemplo.com"),
            ButtonBuilder().setCustomId("help").setLabel("Ajuda").setStyle(ButtonStyle.Secondary),
        ),
        # condicionais
        False and createTextDisplay("não aparece"),
        None,
    )
)

await interaction.response.send_message(
    components=components,
    flags=MessageFlags.IsComponentsV2,
)
```

### 5.2 Components V2 — forma curta (strings automáticas)

```python
from sua_lib import (
    createComponents,
    createContainer,
    createRow,
    createLinkButton,
    Separator,
    ButtonBuilder,
    ButtonStyle,
    MessageFlags,
)

components = createComponents(
    createContainer(
        "#5865F2",
        "# Título da mensagem",
        "Texto normal com **markdown**",
        Separator.Default,
        createRow(
            ButtonBuilder().setCustomId("ok").setLabel("Ok").setStyle(ButtonStyle.Success),
            createLinkButton(label="Site", url="https://exemplo.com"),
        ),
    )
)

await interaction.response.send_message(
    components=components,
    flags=MessageFlags.IsComponentsV2,
)
```

### 5.3 Modal com Label

```python
from sua_lib import (
    createModal,
    createModalFields,
    createLabel,
    createTextInput,
    TextInputStyle,
    ComponentType,
)

modal = createModal(
    customId="registration",
    title="Cadastro",
    components=createModalFields(
        "Preencha os dados abaixo:",
        createLabel(
            "Nome",
            "Seu nome completo",
            {
                "type": ComponentType.TextInput,
                "customId": "name",
                "style": TextInputStyle.Short,
                "required": True,
            },
        ),
        createLabel(
            "Bio",
            "Conte um pouco sobre você",
            {
                "type": ComponentType.TextInput,
                "customId": "bio",
                "style": TextInputStyle.Paragraph,
                "maxLength": 500,
            },
        ),
    ),
)

await interaction.response.send_modal(modal)
```

### 5.4 Modal — forma com createTextInput

```python
from sua_lib import (
    createModal,
    createModalFields,
    createLabel,
    createTextInput,
    TextInputStyle,
)

modal = createModal(
    customId="feedback",
    title="Feedback",
    components=createModalFields(
        createLabel(
            "Mensagem",
            "Descreva o problema ou sugestão",
            createTextInput(
                customId="message",
                style=TextInputStyle.Paragraph,
                minLength=10,
                maxLength=1000,
                required=True,
            ),
        ),
    ),
)

await interaction.response.send_modal(modal)
```

### 5.5 Lendo submit do modal

```python
from sua_lib import modalFieldsToRecord


async def on_modal_submit(interaction):
    fields = modalFieldsToRecord(interaction.fields)
    name = fields["name"]
    bio = fields.get("bio")
    # ...
```

### 5.6 File Upload no modal

```python
from sua_lib import (
    createModal,
    createModalFields,
    createLabel,
    createFileUpload,
)

modal = createModal(
    customId="upload_form",
    title="Envio de arquivo",
    components=createModalFields(
        createLabel(
            "Arquivo",
            "Envie o documento (PDF, PNG...)",
            createFileUpload(customId="file", maxValues=1),
        ),
    ),
)

await interaction.response.send_modal(modal)
```

---

## 6. Referência rápida de tipos

### Components V2 (mensagem)

| Type | Nome | Uso |
|------|------|-----|
| 1 | Action Row | Botões / selects |
| 2 | Button | Interativo |
| 3 | String Select | Select de texto |
| 5–8 | User/Role/Mentionable/Channel Select | Selects de entidades |
| 9 | Section | Texto + accessory |
| 10 | Text Display | Texto markdown |
| 11 | Thumbnail | Accessory de Section |
| 12 | Media Gallery | Grade de mídia |
| 13 | File | Arquivo na mensagem |
| 14 | Separator | Espaço / divisor |
| 17 | Container | Agrupador com accent |

### Modal

| Type | Nome | Uso |
|------|------|-----|
| 4 | Text Input | Input de texto (dentro de Label) |
| 18 | **Label** | Wrapper label + description + component |
| 19 | File Upload | Upload de arquivos (dentro de Label) |
| 21 | Radio Group | Escolha única |
| 22 | Checkbox Group | Múltipla escolha |
| 23 | Checkbox | Sim/não |

### Facilitadores magicyan → Python

| magicyan (TS) | Sua lib (Python) |
|---------------|------------------|
| `createComponents` | `createComponents` |
| `createContainer` | `createContainer` |
| `createTextDisplay` | `createTextDisplay` |
| `createSection` | `createSection` |
| `createSeparator` / `Separator.*` | `createSeparator` / `Separator.*` |
| `createMediaGallery` | `createMediaGallery` |
| `createFile` | `createFile` |
| `createRow` | `createRow` |
| `createLinkButton` | `createLinkButton` |
| `createModal` | `createModal` |
| `createModalFields` | `createModalFields` |
| `createLabel` | `createLabel` |
| `createTextInput` | `createTextInput` |
| `createFileUpload` | `createFileUpload` |
| `modalFieldsToRecord` | `modalFieldsToRecord` |
| `createModalInput` | ❌ deprecated |

---

## Checklist de implementação (sua lib)

- [ ] `createComponents` normaliza string / button / select / attachment / null
- [ ] `createContainer(color, *components)` com accent color
- [ ] `Separator.Large` / `Default` / `Small` como atalhos
- [ ] `createLabel` com overloads: `(label, description, component)` e `(label, component)`
- [ ] TextInput **sempre** dentro de Label no fluxo novo
- [ ] Flag `MessageFlags.IsComponentsV2` documentada e exigida no envio V2
- [ ] `modalFieldsToRecord` para submit
- [ ] Limites (40 components, 4000 chars, etc.) validados ou documentados
- [ ] Zero dependência de import externo para montar UI (tudo em `sua_lib`)
