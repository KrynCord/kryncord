"""Enumerações do protocolo.

Só entram aqui valores que o Discord define como conjunto fechado. Valores
que o Discord pode adicionar a qualquer momento (como nomes de evento)
ficam em `events/names.py`, onde um valor desconhecido não quebra o
parser.
"""

from __future__ import annotations

from enum import IntEnum, IntFlag, StrEnum


class GatewayOpcode(IntEnum):
    """Opcodes do Gateway (client → server e server → client)."""

    DISPATCH = 0
    HEARTBEAT = 1
    IDENTIFY = 2
    PRESENCE_UPDATE = 3
    VOICE_STATE_UPDATE = 4
    RESUME = 6
    RECONNECT = 7
    REQUEST_GUILD_MEMBERS = 8
    INVALID_SESSION = 9
    HELLO = 10
    HEARTBEAT_ACK = 11
    REQUEST_SOUNDS = 31


class CloseCode(IntEnum):
    """Códigos de fechamento relevantes para decidir retomar ou não.

    O Discord usa 4000–4014. Quem **decide** o que fazer com cada um é
    `kryncord.gateway.reconnect.classify_close`, que devolve resume,
    identify ou desistência — a pergunta real não é binária, e uma
    resposta binária mora aqui viraria uma segunda, divergente.
    """

    UNKNOWN_ERROR = 4000
    UNKNOWN_OPCODE = 4001
    DECODE_ERROR = 4002
    NOT_AUTHENTICATED = 4003
    AUTHENTICATION_FAILED = 4004
    ALREADY_AUTHENTICATED = 4005
    INVALID_SEQ = 4007
    RATE_LIMITED = 4008
    SESSION_TIMEOUT = 4009
    INVALID_SHARD = 4010
    SHARDING_REQUIRED = 4011
    INVALID_API_VERSION = 4012
    INVALID_INTENTS = 4013
    DISALLOWED_INTENTS = 4014


class InteractionType(IntEnum):
    """Tipos de interação recebidas."""

    PING = 1
    APPLICATION_COMMAND = 2
    MESSAGE_COMPONENT = 3
    APPLICATION_COMMAND_AUTOCOMPLETE = 4
    MODAL_SUBMIT = 5


class InteractionResponseType(IntEnum):
    """Tipos de resposta a uma interação."""

    PONG = 1
    CHANNEL_MESSAGE_WITH_SOURCE = 4
    DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5
    DEFERRED_UPDATE_MESSAGE = 6
    UPDATE_MESSAGE = 7
    APPLICATION_COMMAND_AUTOCOMPLETE_RESULT = 8
    MODAL = 9
    LAUNCH_ACTIVITY = 12
    """Abre a atividade do app no canal. Exige atividade habilitada no
    Discord Developer Portal — o `callback` aceita, o Discord ignora se
    não houver."""


class ApplicationCommandType(IntEnum):
    """Tipos de comando de aplicação."""

    CHAT_INPUT = 1
    USER = 2
    MESSAGE = 3


class ComponentType(IntEnum):
    """Tipos de componente — os números que vêm em ``component_type``.

    Estes são os valores que o **Discord manda**. Para declarar em
    ``@responder(types=[...])`` use `ResponderType`, que é outra coisa
    (ver ali).

    V1 (1–8) e V2 (9–14, 17) e modal (18–19, 21–23) na mesma tabela,
    porque é a tabela do protocolo — o que muda é **onde** cada tipo é
    aceito, e isso é do `components/validation.py`, não daqui.
    """

    ACTION_ROW = 1
    BUTTON = 2
    STRING_SELECT = 3
    TEXT_INPUT = 4
    USER_SELECT = 5
    ROLE_SELECT = 6
    MENTIONABLE_SELECT = 7
    CHANNEL_SELECT = 8
    SECTION = 9
    TEXT_DISPLAY = 10
    THUMBNAIL = 11
    MEDIA_GALLERY = 12
    FILE = 13
    SEPARATOR = 14
    CONTAINER = 17
    LABEL = 18
    FILE_UPLOAD = 19
    RADIO_GROUP = 21
    CHECKBOX_GROUP = 22
    CHECKBOX = 23

    @property
    def is_select(self) -> bool:
        """Se é algum menu de seleção.

        Só o ``STRING_SELECT`` vem antes do ``USER_SELECT``; qualquer
        menu novo do Discord entra aqui antes de entrar em lugar nenhum
        mais.
        """
        return self in _SELECTS

    @property
    def is_v2(self) -> bool:
        """Se é componente da geração V2 (mensagem = árvore de layouts).

        `ActionRow`/botões/selects são `both` — eles existem nas duas
        gerações, e é isso que faz os dois sistemas convivirem sem
        duplicar builder.
        """
        return self in (
            ComponentType.SECTION,
            ComponentType.TEXT_DISPLAY,
            ComponentType.THUMBNAIL,
            ComponentType.MEDIA_GALLERY,
            ComponentType.FILE,
            ComponentType.SEPARATOR,
            ComponentType.CONTAINER,
        )

    @property
    def is_campo_de_label(self) -> bool:
        """Se é um dos filhos que um `Label` aceita (ideia 15 §3).

        A tabela que o `Label` valida — em um lugar, porque é a mesma
        que o `FileUpload` consulta para saber que só existe em modal.
        """
        return self in (
            ComponentType.TEXT_INPUT,
            ComponentType.STRING_SELECT,
            ComponentType.USER_SELECT,
            ComponentType.ROLE_SELECT,
            ComponentType.MENTIONABLE_SELECT,
            ComponentType.CHANNEL_SELECT,
            ComponentType.FILE_UPLOAD,
            ComponentType.RADIO_GROUP,
            ComponentType.CHECKBOX_GROUP,
            ComponentType.CHECKBOX,
        )


_SELECTS = frozenset(
    {
        ComponentType.STRING_SELECT,
        ComponentType.USER_SELECT,
        ComponentType.ROLE_SELECT,
        ComponentType.MENTIONABLE_SELECT,
        ComponentType.CHANNEL_SELECT,
    }
)


class ButtonStyle(IntEnum):
    """Estilos de botão. `LINK` e `PREMIUM` **não** geram interação."""

    PRIMARY = 1
    SECONDARY = 2
    SUCCESS = 3
    DANGER = 4
    LINK = 5
    PREMIUM = 6


class ChannelType(IntEnum):
    """Tipos de canal — o filtro do `ChannelSelectMenu` e o `type` do
    modelo `Channel`."""

    GUILD_TEXT = 0
    DM = 1
    GUILD_VOICE = 2
    GROUP_DM = 3
    GUILD_CATEGORY = 4
    GUILD_ANNOUNCEMENT = 5
    ANNOUNCEMENT_THREAD = 10
    PUBLIC_THREAD = 11
    PRIVATE_THREAD = 12
    GUILD_STAGE_VOICE = 13
    GUILD_DIRECTORY = 14
    GUILD_FORUM = 15
    GUILD_MEDIA = 16


class MessageFlags(IntFlag):
    """Flags de **mensagem** — inclusive `IS_COMPONENTS_V2`.

    É `MessageFlags`, não `InteractionFlags`: a flag de V2 vai no
    payload da mensagem, e o Discord não define flags "de interação"
    (0015, resposta à V7). `IntFlag` porque o Discord recebe o OU de
    várias, igual às permissões.
    """

    CROSSPOSTED = 1 << 0
    IS_CROSSPOST = 1 << 1
    SUPPRESS_EMBEDS = 1 << 2
    SOURCE_MESSAGE_DELETED = 1 << 3
    URGENT = 1 << 4
    HAS_THREAD = 1 << 5
    EPHEMERAL = 1 << 6
    LOADING = 1 << 7
    FAILED_TO_MENTION_SOME_ROLES_IN_THREAD = 1 << 8
    SUPPRESS_NOTIFICATIONS = 1 << 12
    IS_VOICE_MESSAGE = 1 << 13
    IS_COMPONENTS_V2 = 1 << 15


class ResponderType(StrEnum):
    """O que um ``@responder`` atende.

    **`StrEnum`, não `IntEnum`** — e isso não é preferência, é
    obrigatório. Os dois namespaces do Discord colidem:

    ```text
    ComponentType.USER_SELECT     = 5     InteractionType.MODAL_SUBMIT = 5
    ComponentType.TEXT_INPUT      = 4     InteractionType.AUTOCOMPLETE = 4
    ```

    Um `IntEnum` único obrigaria a mapear os dois num só número, e a
    colisão faria ``types=[ResponderType.MODAL]`` casar com um campo de
    texto — falha silenciosa, no registro, sem erro em lugar nenhum.
    """

    ACTION_ROW = "action_row"
    BUTTON = "button"
    STRING_SELECT = "string_select"
    TEXT_INPUT = "text_input"
    USER_SELECT = "user_select"
    ROLE_SELECT = "role_select"
    MENTIONABLE_SELECT = "mentionable_select"
    CHANNEL_SELECT = "channel_select"
    MODAL_SUBMIT = "modal_submit"
    AUTOCOMPLETE = "autocomplete"

    @classmethod
    def modal(cls) -> ResponderType:
        """Alias legível de `MODAL_SUBMIT`.

        A ideia `07` escreve `types=[ResponderType.MODAL]`. Um alias de
        classe não pode ser membro de `StrEnum` sem virar um valor
        duplicado — e valor duplicado é o que a decisão `0023` R4
        acabou de proibir por construção.
        """
        return cls.MODAL_SUBMIT

    @classmethod
    def de_interacao(cls, tipo_interacao: int, component_type: int | None = None) -> ResponderType:
        """Qual `ResponderType` uma interação representa.

        `tipo_interacao` é ``Interaction.type``; `component_type` é
        ``data.component_type``, presente só em ``MESSAGE_COMPONENT``.
        """
        if tipo_interacao == InteractionType.MESSAGE_COMPONENT:
            if component_type is None:
                raise ValueError(
                    "interação MESSAGE_COMPONENT sem data.component_type — payload malformado"
                )
            return cls(ComponentType(component_type).name.lower())
        if tipo_interacao == InteractionType.MODAL_SUBMIT:
            return cls.MODAL_SUBMIT
        if tipo_interacao == InteractionType.APPLICATION_COMMAND_AUTOCOMPLETE:
            return cls.AUTOCOMPLETE
        raise ValueError(
            f"interação tipo {tipo_interacao} não tem ResponderType — só MESSAGE_COMPONENT "
            f"(3), MODAL_SUBMIT (5) e AUTOCOMPLETE (4) têm responder"
        )

    @classmethod
    def selects(cls) -> tuple[ResponderType, ...]:
        """Todos os menus de seleção.

        Um responder que atende "qualquer select" lista estes em vez de
        cinco nomes na mão — e é a lista que cresce quando o Discord
        adicionar um menu.
        """
        return (
            cls.STRING_SELECT,
            cls.USER_SELECT,
            cls.ROLE_SELECT,
            cls.MENTIONABLE_SELECT,
            cls.CHANNEL_SELECT,
        )


class Permission(StrEnum):
    """Permissões, em formato `snake_case` para a API aceitar direto.

    O Discord aceita tanto o nome quanto o bit. Usar o nome torna o
    código legível e a validação trivial.
    """

    CREATE_INSTANT_INVITE = "create_instant_invite"
    KICK_MEMBERS = "kick_members"
    BAN_MEMBERS = "ban_members"
    ADMINISTRATOR = "administrator"
    MANAGE_CHANNELS = "manage_channels"
    MANAGE_GUILD = "manage_guild"
    ADD_REACTIONS = "add_reactions"
    VIEW_AUDIT_LOG = "view_audit_log"
    PRIORITY_SPEAKER = "priority_speaker"
    STREAM = "stream"
    VIEW_CHANNEL = "view_channel"
    SEND_MESSAGES = "send_messages"
    SEND_TTS_MESSAGES = "send_tts_messages"
    MANAGE_MESSAGES = "manage_messages"
    EMBED_LINKS = "embed_links"
    ATTACH_FILES = "attach_files"
    READ_MESSAGE_HISTORY = "read_message_history"
    MENTION_EVERYONE = "mention_everyone"
    USE_EXTERNAL_EMOJIS = "use_external_emojis"
    VIEW_GUILD_INSIGHTS = "view_guild_insights"
    CONNECT = "connect"
    SPEAK = "speak"
    MUTE_MEMBERS = "mute_members"
    DEAFEN_MEMBERS = "deafen_members"
    MOVE_MEMBERS = "move_members"
    USE_VAD = "use_vad"
    CHANGE_NICKNAME = "change_nickname"
    MANAGE_NICKNAMES = "manage_nicknames"
    MANAGE_ROLES = "manage_roles"
    MANAGE_WEBHOOKS = "manage_webhooks"
    MANAGE_GUILD_EXPRESSIONS = "manage_guild_expressions"
    USE_APPLICATION_COMMANDS = "use_application_commands"
    REQUEST_TO_SPEAK = "request_to_speak"
    MANAGE_EVENTS = "manage_events"
    MANAGE_THREADS = "manage_threads"
    CREATE_PUBLIC_THREADS = "create_public_threads"
    CREATE_PRIVATE_THREADS = "create_private_threads"
    USE_EXTERNAL_STICKERS = "use_external_stickers"
    SEND_MESSAGES_IN_THREADS = "send_messages_in_threads"
    USE_EMBEDDED_ACTIVITIES = "use_embedded_activities"
    MODERATE_MEMBERS = "moderate_members"

    VIEW_CREATOR_MONETIZATION_ANALYTICS = "view_creator_monetization_analytics"
    USE_SOUNDBOARD = "use_soundboard"
    CREATE_GUILD_EXPRESSIONS = "create_guild_expressions"
    USE_EXTERNAL_SOUNDS = "use_external_sounds"
    SEND_VOICE_MESSAGES = "send_voice_messages"

    SEND_POLLS = "send_polls"
    USE_EXTERNAL_APPS = "use_external_apps"


def permission_names() -> list[str]:
    """Nomes de permissão, para preencher `choices` de autocomplete."""
    return [permission.value for permission in Permission]
