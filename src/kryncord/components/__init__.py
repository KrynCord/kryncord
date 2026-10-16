"""Builders e validação de componentes de interface.

A separação por **tipo de componente** (o que muda na API do Discord)
com validação isolada num módulo só — porque a validação é a parte que
precisa de caminho na mensagem de erro (`rows[2].components[3]`).

Dois sistemas, uma casa: V1 (`ActionRow` + botões/selects + embeds) e
V2 (`Container`/`Section`/`TextDisplay`) convivem porque os botões e
selects são `era="both"` — o mesmo builder nas duas gerações. A
fronteira entre elas é um lugar só: `validation.validate_message`, a
tabela da ideia 18 §4.

Componente novo só entra aqui depois de confirmar o formato oficial.
"""

from kryncord.components.base import Component, Era
from kryncord.components.buttons import Button, create_link_button
from kryncord.components.choices import Checkbox, CheckboxGroup, RadioGroup
from kryncord.components.colors import AccentColor, parse_color, random_color
from kryncord.components.displays import (
    Container,
    File,
    MediaGallery,
    MediaGalleryItem,
    Section,
    Separator,
    SeparatorSize,
    TextDisplay,
    Thumbnail,
    create_container,
    create_file,
    create_media_gallery,
    create_section,
    create_separator,
    create_text_display,
    create_thumbnail,
)
from kryncord.components.inputs import (
    Label,
    TextInput,
    TextInputStyle,
    create_label,
    create_text_input,
)
from kryncord.components.modals import Modal, create_modal, create_modal_fields
from kryncord.components.rows import (
    ActionRow,
    create_components,
    create_components_rows,
    create_row,
)
from kryncord.components.selects import (
    ChannelSelectMenu,
    MentionableSelectMenu,
    RoleSelectMenu,
    SelectOption,
    StringSelectMenu,
    UserSelectMenu,
    create_channel_select,
    create_mentionable_select,
    create_role_select,
    create_string_select,
    create_user_select,
)
from kryncord.components.uploads import FileUpload, create_file_upload
from kryncord.components.validation import (
    parse_flags,
    tem_v2,
    validate_components,
    validate_message,
    validate_modal,
    validate_rows,
)

# Agrupado por categoria de propósito, como o `__all__` da raiz — ver
# o comentário lá.
__all__ = [  # noqa: RUF022
    # base
    "Component",
    "Era",
    # botões
    "Button",
    "create_link_button",
    # selects
    "ChannelSelectMenu",
    "MentionableSelectMenu",
    "RoleSelectMenu",
    "SelectOption",
    "StringSelectMenu",
    "UserSelectMenu",
    "create_channel_select",
    "create_mentionable_select",
    "create_role_select",
    "create_string_select",
    "create_user_select",
    # campos de modal
    "Checkbox",
    "CheckboxGroup",
    "FileUpload",
    "Label",
    "RadioGroup",
    "TextInput",
    "TextInputStyle",
    "create_file_upload",
    "create_label",
    "create_text_input",
    # modal
    "Modal",
    "create_modal",
    "create_modal_fields",
    # rows e montagem
    "ActionRow",
    "create_components",
    "create_components_rows",
    "create_row",
    # displays V2
    "Container",
    "File",
    "MediaGallery",
    "MediaGalleryItem",
    "Section",
    "Separator",
    "SeparatorSize",
    "TextDisplay",
    "Thumbnail",
    "create_container",
    "create_file",
    "create_media_gallery",
    "create_section",
    "create_separator",
    "create_text_display",
    "create_thumbnail",
    # cores
    "AccentColor",
    "parse_color",
    "random_color",
    # validação
    "parse_flags",
    "tem_v2",
    "validate_components",
    "validate_message",
    "validate_modal",
    "validate_rows",
]
