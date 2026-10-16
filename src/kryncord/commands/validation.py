"""Validação de definição de comando — antes de qualquer requisição.

A regra é uma só: **o erro aparece na importação, não no `sync()`**.
Um comando inválido descoberto no meio de um bulk PUT já mandou metade
da lista, e o Discord responde 400 sem dizer qual dos vinte comandos
estava errado.

Cada regra aqui existe porque o Discord recusa com 400. A mensagem
cita o campo e o comando — sem isso, o erro não diz onde procurar.
"""

from __future__ import annotations

import re
from typing import Any

from kryncord.commands.definition import CommandDefinition
from kryncord.commands.option import (
    MAX_CHOICES,
    MAX_OPCOES,
    MAX_SUBCOMANDOS_POR_GRUPO,
    Option,
    OptionType,
)
from kryncord.enums import ApplicationCommandType
from kryncord.errors import DefinitionError

#: O Discord aceita estes caracteres no nome, e nada além. A expressão
#: é o que ele publica — mudar sem consultar é inventar regra. O espaço
#: é aceito no nome raiz, e não em subcomando.
_NOME = re.compile(r"^[-_\w .]{1,32}$", re.UNICODE)
_DESCRICAO = re.compile(r"^.{1,100}$", re.DOTALL)


def validate_definition(definition: CommandDefinition) -> None:
    """Valida a definição inteira, levantando `DefinitionError`."""
    _valida_nome(definition.name, "name")

    if definition.type is ApplicationCommandType.CHAT_INPUT:
        _valida_chat_input(definition)
    else:
        _valida_context_menu(definition)

    _valida_options(definition.options, onde=definition.name)


def _valida_chat_input(d: CommandDefinition) -> None:
    """CHAT_INPUT exige descrição; os outros dois tipos a proíbem."""
    if not d.description:
        raise DefinitionError(
            f"comando {d.name!r}: CHAT_INPUT exige description (1 a 100 caracteres). "
            f"Para menu de contexto use type=ApplicationCommandType.USER ou .MESSAGE, "
            f"que não aceitam descrição."
        )
    if not _DESCRICAO.match(d.description):
        raise DefinitionError(
            f"comando {d.name!r}: description com {len(d.description)} caracteres; "
            f"o Discord aceita de 1 a 100"
        )


def _valida_context_menu(d: CommandDefinition) -> None:
    """USER e MESSAGE não têm descrição nem opções.

    O Discord recusa os dois com 400 — e a mensagem dele é
    "Invalid application command", sem dizer qual campo. Validar aqui
    é o único jeito de apontar o culpado.
    """
    if d.description:
        raise DefinitionError(
            f"comando {d.name!r}: type={d.type.name} não aceita description "
            f"(recebido {d.description!r}). Só CHAT_INPUT tem descrição."
        )
    if d.options:
        raise DefinitionError(
            f"comando {d.name!r}: type={d.type.name} não aceita options "
            f"(recebidos {len(d.options)}). O alvo vem do clique, não de opção."
        )


def _valida_options(options: tuple[Option, ...], *, onde: str) -> None:
    if len(options) > MAX_OPCOES:
        raise DefinitionError(
            f"comando {onde!r}: {len(options)} opções; o Discord aceita até {MAX_OPCOES}"
        )

    nomes: set[str] = set()
    for option in options:
        if option.name in nomes:
            raise DefinitionError(f"comando {onde!r}: opção {option.name!r} duplicada")
        nomes.add(option.name)

        _valida_nome(option.name, f"opção de {onde!r}")
        _valida_sub_options(option, onde=onde)

        if option.type is OptionType.SUB_COMMAND:
            if option.choices or option.autocomplete:
                raise DefinitionError(
                    f"comando {onde!r}: subcomando {option.name!r} não tem choices nem "
                    f"autocomplete — ele tem options próprias"
                )
            _valida_options(option.options, onde=f"{onde} {option.name}")
            continue

        if option.type is OptionType.SUB_COMMAND_GROUP:
            _valida_grupo(option, onde=onde)
            continue

        if option.choices and len(option.choices) > MAX_CHOICES:
            raise DefinitionError(
                f"comando {onde!r}: opção {option.name!r} com {len(option.choices)} "
                f"escolhas; o Discord aceita até {MAX_CHOICES}"
            )

        if not option.description:
            raise DefinitionError(f"comando {onde!r}: opção {option.name!r} precisa de description")
        if not _DESCRICAO.match(option.description):
            raise DefinitionError(
                f"comando {onde!r}: opção {option.name!r} com descrição de "
                f"{len(option.description)} caracteres; o Discord aceita 1 a 100"
            )

        if option.choices and option.type not in (
            OptionType.STRING,
            OptionType.INTEGER,
            OptionType.NUMBER,
        ):
            raise DefinitionError(
                f"comando {onde!r}: opção {option.name!r} com choices é só STRING, "
                f"INTEGER ou NUMBER — {option.type.name} aceita entidade, não lista fixa"
            )

        for c in option.choices:
            if not isinstance(c, dict) or "name" not in c or "value" not in c:
                raise DefinitionError(
                    f"comando {onde!r}: escolha de {option.name!r} precisa de name e "
                    f"value — use kryncord.choice(nome, valor)"
                )

        if option.min_value is not None and option.type not in (
            OptionType.INTEGER,
            OptionType.NUMBER,
        ):
            raise DefinitionError(
                f"comando {onde!r}: opção {option.name!r} com min_value é só INTEGER ou NUMBER"
            )


def _valida_sub_options(option: Option, *, onde: str) -> None:
    """Opções de valor não podem ter `options` próprias; subcomando
    não pode ter valor."""
    if option.type in (OptionType.SUB_COMMAND, OptionType.SUB_COMMAND_GROUP):
        if option.choices or option.autocomplete or option.min_value is not None:
            raise DefinitionError(
                f"comando {onde!r}: subcomando {option.name!r} não aceita choices, "
                f"autocomplete nem min_value"
            )
        return

    if option.options:
        raise DefinitionError(
            f"comando {onde!r}: opção {option.name!r} ({option.type.name}) não tem "
            f"options — só SUB_COMMAND e SUB_COMMAND_GROUP têm"
        )


def _valida_grupo(grupo: Option, *, onde: str) -> None:
    """Grupo sem subcommand falha o sync inteiro — e o erro tem que
    apontar o grupo, não o comando raiz."""
    subcomandos = [o for o in grupo.options if o.type is OptionType.SUB_COMMAND]
    if not subcomandos:
        raise DefinitionError(
            f"comando {onde!r}: grupo {grupo.name!r} sem subcommand. Um grupo existe "
            f"só para agrupar subcomandos — sozinho o Discord recusa."
        )
    if len(grupo.options) > MAX_SUBCOMANDOS_POR_GRUPO:
        raise DefinitionError(
            f"comando {onde!r}: grupo {grupo.name!r} com {len(grupo.options)} "
            f"subcomandos; o Discord aceita até {MAX_SUBCOMANDOS_POR_GRUPO}"
        )
    nomes = [o.name for o in grupo.options]
    if len(nomes) != len(set(nomes)):
        raise DefinitionError(f"comando {onde!r}: grupo {grupo.name!r} com subcomando duplicado")


def _valida_nome(nome: str, onde: str) -> None:
    if not nome:
        raise DefinitionError(f"{onde}: nome vazio")
    if len(nome) > 32:
        raise DefinitionError(
            f"{onde}: {nome!r} com {len(nome)} caracteres; o Discord aceita até 32"
        )
    if not _NOME.match(nome):
        raise DefinitionError(f"{onde}: {nome!r} tem caractere que o Discord não aceita no nome")


def options_para_payload(options: tuple[Option, ...]) -> list[dict[str, Any]]:
    """Serializa para o payload, sem validar — a validação já passou."""
    return [o.to_payload() for o in options]
