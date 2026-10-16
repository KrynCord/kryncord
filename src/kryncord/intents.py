"""Intents solicitados ao Gateway.

Intents são bits. Pedir bits que a aplicação não tem permissão para
usar faz o Discord rejeitar o Identify com `DISALLOWED_INTENTS` — o erro
só aparece depois de conectar. Validar antes economiza um ciclo de
reconexão confuso.

Os valores são **contrato de protocolo**: bits esparsos, não uma
sequência contínua. Trocar um bit de lugar não quebra o import, quebra
silenciosamente o bot inteiro.
"""

from __future__ import annotations

from enum import IntFlag

#: Intents que exigem ativação manual no portal de desenvolvedores.
#: Sem isso, o Discord responde `DISALLOWED_INTENTS` no Identify.
PRIVILEGED_INTENTS = (
    "GUILD_MEMBERS",
    "GUILD_PRESENCES",
    "MESSAGE_CONTENT",
)


class Intents(IntFlag):
    """Bits de intent, conforme a documentação oficial do Discord."""

    # --- pré-definidos ---
    GUILDS = 1 << 0
    GUILD_MEMBERS = 1 << 1  # privileged
    GUILD_MODERATION = 1 << 2
    GUILD_EMOJIS_AND_STICKERS = 1 << 3
    GUILD_INTEGRATIONS = 1 << 4
    GUILD_WEBHOOKS = 1 << 5
    GUILD_INVITES = 1 << 6
    GUILD_VOICE_STATES = 1 << 7
    GUILD_PRESENCES = 1 << 8  # privileged
    GUILD_MESSAGES = 1 << 9
    GUILD_MESSAGE_REACTIONS = 1 << 10
    GUILD_MESSAGE_TYPING = 1 << 11
    DIRECT_MESSAGES = 1 << 12
    DIRECT_MESSAGE_REACTIONS = 1 << 13
    DIRECT_MESSAGE_TYPING = 1 << 14
    MESSAGE_CONTENT = 1 << 15  # privileged
    GUILD_SCHEDULED_EVENTS = 1 << 16
    AUTO_MODERATION_CONFIGURATION = 1 << 20
    AUTO_MODERATION_EXECUTION = 1 << 21
    GUILD_MESSAGE_POLLS = 1 << 24
    DIRECT_MESSAGE_POLLS = 1 << 25

    @classmethod
    def default(cls) -> Intents:
        """Conjunto mínimo para um bot que só responde a comandos.

        Não inclui nenhum privileged intent. Um bot que só usa slash
        commands precisa apenas de `GUILDS` — eventos de interação não
        dependem de intent nenhum.
        """
        return cls.GUILDS

    @classmethod
    def privileged(cls) -> Intents:
        """Os três intents que exigem ativação manual."""
        return cls.GUILD_MEMBERS | cls.GUILD_PRESENCES | cls.MESSAGE_CONTENT

    @classmethod
    def all_non_privileged(cls) -> Intents:
        """Todos os intents que não exigem ativação no portal."""
        privileged = cls.privileged()
        value = 0
        for intent in cls:
            if (intent & privileged) == 0:
                value |= intent
        return cls(value)

    def missing_privileged(self, enabled: Intents) -> list[str]:
        """Quais privileged intents `self` pede e `enabled` não concede.

        Retorna nomes legíveis para a mensagem de erro. Lista vazia
        significa que o Identify vai passar.
        """
        requested = self & self.privileged() & ~enabled
        return [intent.name for intent in requested if intent.name]

    def validate(self, enabled: Intents | None = None) -> None:
        """Levanta `ValueError` se faltar permissão para algum intent.

        `enabled` é o conjunto que o portal concedeu. Se `None`, pula a
        checagem — a validação fica para o Discord rejeitar.
        """
        if enabled is None:
            return
        missing = self.missing_privileged(enabled)
        if missing:
            raise ValueError(
                "Intents privileged solicitados mas não habilitados no portal: "
                f"{', '.join(missing)}. Ative em "
                "https://discord.com/developers/applications → Bot → Privileged Gateway Intents."
            )

    def to_payload(self) -> int:
        """Valor inteiro enviado no Identify."""
        return int(self)
