"""Definição, validação, registro e sincronização de comandos.

Validação acontece na **importação**, não no dispatch. Nome inválido,
opção duplicada ou grupo sem subcommand derrubam o startup com mensagem
apontando o comando — não aparecem como "comando não encontrado" quando
o usuário digita `/`.

A separação de papéis:

| Módulo | Dono |
|---|---|
| `option` | `Option` — o parâmetro de um slash command |
| `definition` | `CommandDefinition` — o payload serializável |
| `validation` | regras por tipo, antes de qualquer requisição |
| `instance` | `CommandInstance` — o que o usuário encadeia |
| `registry` | chave `(type, name, scope)` e o singleton por payload |
"""

from kryncord.commands.autocomplete import (
    MAX_ESCOLHAS,
    AutocompleteContext,
    dispatch_autocomplete,
    foco_de,
    normalize_choices,
)
from kryncord.commands.context import CommandContext, OptionsAccessor
from kryncord.commands.decorators import command, create_command
from kryncord.commands.definition import CommandDefinition, CommandScope
from kryncord.commands.dispatch import dispatch_application_command, instancia_de
from kryncord.commands.instance import CommandInstance
from kryncord.commands.option import Option, OptionType, choice
from kryncord.commands.registry import CommandKey, CommandRegistry
from kryncord.commands.sync import CommandSync, SyncAction, SyncReport
from kryncord.commands.validation import validate_definition

__all__ = [
    "MAX_ESCOLHAS",
    "AutocompleteContext",
    "CommandContext",
    "CommandDefinition",
    "CommandInstance",
    "CommandKey",
    "CommandRegistry",
    "CommandScope",
    "CommandSync",
    "Option",
    "OptionType",
    "OptionsAccessor",
    "SyncAction",
    "SyncReport",
    "choice",
    "command",
    "create_command",
    "dispatch_application_command",
    "dispatch_autocomplete",
    "foco_de",
    "instancia_de",
    "normalize_choices",
    "validate_definition",
]
