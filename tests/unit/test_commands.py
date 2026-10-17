"""Fundação de `commands/`: Option, CommandDefinition, validação,
CommandInstance e CommandRegistry.

O fio condutor: **o erro aparece na importação, não no sync**. Tudo que
o Discord recusaria com 400 tem que falhar aqui, com o campo e o
comando na mensagem.
"""

from __future__ import annotations

import pytest

from kryncord.commands import (
    CommandDefinition,
    CommandInstance,
    CommandRegistry,
    Option,
    OptionType,
    choice,
    validate_definition,
)
from kryncord.enums import ApplicationCommandType
from kryncord.errors import CommandDefinitionError, DefinitionError
from kryncord.interactions import AutocompleteInteraction, CommandInteraction
from kryncord.permissions import Permissions


def _chat(
    nome: str = "ping", descricao: str = "responde pong", **kwargs: object
) -> CommandDefinition:
    return CommandDefinition(name=nome, description=descricao, **kwargs)  # type: ignore[arg-type]


def _handler(ctx: object = None) -> None:
    """Responde pong."""


# --------------------------------------------------------------------------
# Option
# --------------------------------------------------------------------------


class TestOption:
    def test_atalhos_criam_o_tipo_certo(self) -> None:
        assert Option.string("a").type is OptionType.STRING
        assert Option.integer("a").type is OptionType.INTEGER
        assert Option.number("a").type is OptionType.NUMBER
        assert Option.boolean("a").type is OptionType.BOOLEAN
        assert Option.user("a").type is OptionType.USER
        assert Option.channel("a").type is OptionType.CHANNEL
        assert Option.role("a").type is OptionType.ROLE
        assert Option.mentionable("a").type is OptionType.MENTIONABLE
        assert Option.attachment("a").type is OptionType.ATTACHMENT
        assert Option.sub_command("a").type is OptionType.SUB_COMMAND
        assert Option.group("a").type is OptionType.SUB_COMMAND_GROUP

    def test_name_vazio_e_erro(self) -> None:
        with pytest.raises(DefinitionError, match="name"):
            Option("", OptionType.STRING)

    def test_autocomplete_e_choices_nao_combinam(self) -> None:
        """O Discord recusa os dois juntos — e a mensagem dele não diz
        qual campo."""
        with pytest.raises(DefinitionError, match="não combinam"):
            Option.string("cor", autocomplete=True, choices=(choice("a", 1),))

    def test_required_e_choices_nao_combinam(self) -> None:
        """Escolha fixa já decide o valor; required não muda nada."""
        with pytest.raises(DefinitionError, match="não combinam"):
            Option.string("cor", required=True, choices=(choice("a", 1),))

    def test_min_maior_que_max_e_erro(self) -> None:
        with pytest.raises(DefinitionError, match="min_value"):
            Option.integer("n", min_value=10, max_value=1)

    def test_payload_omite_o_que_nao_foi_declarado(self) -> None:
        """Mandar `choices=[]` é diferente de não mandar, e o Discord
        reclama do primeiro."""
        payload = Option.string("nome", "um nome").to_payload()

        assert payload == {
            "name": "nome",
            "type": 3,
            "description": "um nome",
            "required": False,
        }
        assert "choices" not in payload
        assert "autocomplete" not in payload
        assert "min_value" not in payload

    def test_choice_aceita_localizations_como_kwargs(self) -> None:
        """A forma curta: sem aninhar dict na chamada."""
        assert choice("Sim", True, **{"pt-BR": "Sim", "en-US": "Yes"}) == {
            "name": "Sim",
            "value": True,
            "name_localizations": {"pt-BR": "Sim", "en-US": "Yes"},
        }


# --------------------------------------------------------------------------
# Validação por tipo — 0022
# --------------------------------------------------------------------------


class TestValidacaoPorTipo:
    def test_chat_input_exige_descricao(self) -> None:
        with pytest.raises(DefinitionError, match="exige description"):
            validate_definition(_chat(descricao=""))

    def test_chat_input_aceita_opcoes(self) -> None:
        validate_definition(_chat(options=(Option.string("a", "b"),)))

    def test_user_nao_aceita_descricao(self) -> None:
        """O Discord recusa com 400 e a mensagem dele é 'Invalid
        application command' — sem dizer qual campo."""
        d = CommandDefinition(
            name="menu", description="não deveria estar aqui", type=ApplicationCommandType.USER
        )
        with pytest.raises(DefinitionError, match="não aceita description"):
            validate_definition(d)

    def test_user_nao_aceita_options(self) -> None:
        d = CommandDefinition(
            name="menu",
            description="",
            type=ApplicationCommandType.USER,
            options=(Option.string("a", "b"),),
        )
        with pytest.raises(DefinitionError, match="não aceita options"):
            validate_definition(d)

    def test_message_nao_aceita_descricao_nem_options(self) -> None:
        d = CommandDefinition(name="copiar", description="x", type=ApplicationCommandType.MESSAGE)
        with pytest.raises(DefinitionError, match="não aceita description"):
            validate_definition(d)

    def test_context_menu_valido_passa(self) -> None:
        validate_definition(
            CommandDefinition(name="menu", description="", type=ApplicationCommandType.USER)
        )
        validate_definition(
            CommandDefinition(name="copiar", description="", type=ApplicationCommandType.MESSAGE)
        )


class TestValidacaoDeOptions:
    def test_descricao_da_opcao_e_obrigatoria(self) -> None:
        with pytest.raises(DefinitionError, match="precisa de description"):
            validate_definition(_chat(options=(Option.string("a"),)))

    def test_opcao_duplicada(self) -> None:
        with pytest.raises(DefinitionError, match="duplicada"):
            validate_definition(_chat(options=(Option.string("a", "x"), Option.string("a", "y"))))

    def test_mais_de_25_opcoes(self) -> None:
        ops = tuple(Option.string(f"o{i}", "d") for i in range(26))
        with pytest.raises(DefinitionError, match="25"):
            validate_definition(_chat(options=ops))

    def test_mais_de_25_choices(self) -> None:
        muitas = Option.string("c", "d", choices=tuple(choice(str(i), i) for i in range(26)))
        with pytest.raises(DefinitionError, match="25"):
            validate_definition(_chat(options=(muitas,)))

    def test_choices_somente_em_tipos_de_valor(self) -> None:
        """USER aceita entidade, não lista fixa — o Discord recusa."""
        with pytest.raises(DefinitionError, match="só STRING"):
            validate_definition(_chat(options=(Option.user("u", "d", choices=(choice("a", 1),)),)))

    def test_min_value_somente_numerico(self) -> None:
        with pytest.raises(DefinitionError, match="min_value"):
            validate_definition(_chat(options=(Option.string("s", "d", min_value=1),)))

    def test_opcao_de_valor_nao_pode_ter_options(self) -> None:
        op = Option(
            "s",
            OptionType.STRING,
            "d",
            options=(Option.string("interna", "x"),),
        )
        with pytest.raises(DefinitionError, match="não tem options"):
            validate_definition(_chat(options=(op,)))


class TestValidacaoDeGrupos:
    def test_grupo_sem_subcommand_falha(self) -> None:
        """O erro tem que apontar o grupo, não o comando raiz — e antes
        de qualquer requisição, não no meio do bulk."""
        d = _chat(options=(Option.group("papel", "gerencia papeis"),))
        with pytest.raises(DefinitionError, match="grupo 'papel' sem subcommand"):
            validate_definition(d)

    def test_grupo_com_subcommand_passa(self) -> None:
        d = _chat(
            options=(
                Option.group(
                    "papel",
                    "gerencia papeis",
                    options=(Option.sub_command("add", "adiciona"),),
                ),
            )
        )
        validate_definition(d)

    def test_subcommand_com_choices_e_erro(self) -> None:
        """Subcomando tem options próprias, não valor."""
        d = _chat(options=(Option.sub_command("x", "d", choices=(choice("a", 1),)),))
        with pytest.raises(DefinitionError, match="não aceita choices"):
            validate_definition(d)

    def test_nome_muito_longo(self) -> None:
        with pytest.raises(DefinitionError, match="32"):
            validate_definition(_chat(nome="a" * 33))

    def test_nome_com_caractere_invalido(self) -> None:
        with pytest.raises(DefinitionError, match="caractere"):
            validate_definition(_chat(nome="ping!"))


# --------------------------------------------------------------------------
# CommandDefinition
# --------------------------------------------------------------------------


class TestDefinition:
    def test_payload_omite_nao_declarado(self) -> None:
        assert _chat().to_payload() == {
            "name": "ping",
            "description": "responde pong",
            "type": 1,
        }

    def test_payload_inclui_o_declarado(self) -> None:
        d = CommandDefinition(
            name="mod",
            description="moderação",
            default_member_permissions=Permissions.KICK_MEMBERS,
            dm_permission=False,
            nsfw=True,
            options=(Option.string("alvo", "quem"),),
        )
        payload = d.to_payload()

        assert payload["default_member_permissions"] == str(int(Permissions.KICK_MEMBERS))
        assert payload["dm_permission"] is False
        assert payload["nsfw"] is True
        assert payload["options"][0]["name"] == "alvo"

    def test_permissoes_zero_e_diferente_de_none(self) -> None:
        """`None` é "sem restrição"; `Permissions(0)` é "ninguém".
        Fundir os dois abriria o comando para todo mundo quando o autor
        quis fechar para staff."""
        restrito_zero = CommandDefinition("a", "b", default_member_permissions=Permissions(0))
        sem_restricao = CommandDefinition("a", "b", default_member_permissions=None)

        assert "default_member_permissions" in restrito_zero.to_payload()
        assert "default_member_permissions" not in sem_restricao.to_payload()

    def test_scope_none_e_global(self) -> None:
        assert _chat().is_global is True
        assert _chat(scope=123).is_global is False

    def test_com_escopo_mantem_o_resto(self) -> None:
        base = _chat(default_member_permissions=Permissions.KICK_MEMBERS, nsfw=True)
        copia = base.com_escopo(999)

        assert copia.scope == 999
        assert copia.name == base.name
        assert copia.default_member_permissions is base.default_member_permissions
        assert copia.nsfw is True

    def test_igualdade_profunda_funciona(self) -> None:
        """É o que o `sync()` do 0018 usa para o diff — sem hash, sem
        comparação manual campo a campo."""
        assert _chat() == _chat()
        assert _chat() != _chat(descricao="outra")


# --------------------------------------------------------------------------
# CommandInstance
# --------------------------------------------------------------------------


async def _add(interaction: CommandInteraction, cargo: object = None) -> None:
    """adiciona um papel"""


async def _remove(interaction: CommandInteraction, cargo: object = None) -> None:
    """remove um papel"""


class TestInstance:
    def test_definition_e_propriedade(self) -> None:
        """`create_command` devolve instância; a definição é o que se
        lê, não o que se encadeia — resolve a contradição 02 §2 × 04 §3
        do 0011."""
        inst = CommandInstance(_chat(), _handler)

        assert isinstance(inst.definition, CommandDefinition)
        assert inst.name == "ping"
        assert inst.type is ApplicationCommandType.CHAT_INPUT
        assert inst.scope is None

    def test_sub_adiciona_opcao(self) -> None:
        inst = CommandInstance(_chat("papel", "gerencia"), _handler)
        inst.sub("add", _add)

        tipos = [o.type for o in inst.definition.options]
        assert tipos == [OptionType.SUB_COMMAND]
        assert inst.definition.options[0].name == "add"

    def test_sub_duplicado_e_erro(self) -> None:
        inst = CommandInstance(_chat("papel", "gerencia"), _handler)
        inst.sub("add", _add)

        with pytest.raises(CommandDefinitionError, match="duplicado"):
            inst.sub("add", _remove)

    def test_sub_sucessivos_nao_duplicam(self) -> None:
        """Regressão: `_rebuild` somava nas opções atuais, que já
        continham o sintetizado da declaração anterior. Dois `sub()`
        viravam três opções — e o segundo grupo já não tinha os
        subcomandos do primeiro."""
        inst = CommandInstance(_chat("papel", "gerencia"), _handler)
        inst.sub("add", _add)
        inst.sub("remove", _remove)

        assert [o.name for o in inst.definition.options] == ["add", "remove"]

    def test_add_sucessivos_nao_duplicam_grupo(self) -> None:
        """Mesmo motivo do anterior, pelo caminho do grupo."""
        inst = CommandInstance(_chat("papel", "gerencia"), _handler)
        inst.group("papel", "gerencia papeis").add("add", _add).add("remove", _remove)

        grupos = [o for o in inst.definition.options if o.type is OptionType.SUB_COMMAND_GROUP]
        assert len(grupos) == 1
        assert [s.name for s in grupos[0].options] == ["add", "remove"]

    def test_grupo_com_varios_subcomandos(self) -> None:
        inst = CommandInstance(_chat("papel", "gerencia"), _handler)
        inst.group("papel", "gerencia papeis").add("add", _add).add("remove", _remove)

        grupo = inst.definition.options[0]
        assert grupo.type is OptionType.SUB_COMMAND_GROUP
        assert [o.name for o in grupo.options] == ["add", "remove"]

    def test_descricao_do_sub_vem_do_docstring(self) -> None:
        """A descrição já está escrita no docstring — pedir duas vezes é
        garantia de divergência."""
        inst = CommandInstance(_chat("papel", "gerencia"), _handler)
        inst.sub("add", _add)

        assert inst.definition.options[0].description == "adiciona um papel"

    def test_descricao_do_grupo_e_a_declarada(self) -> None:
        inst = CommandInstance(_chat("papel", "gerencia"), _handler)
        inst.group("papel", "gerencia papeis").add("add", _add)

        assert inst.definition.options[0].description == "gerencia papeis"

    def test_descricao_de_dois_grupos_nao_se_cruzam(self) -> None:
        """Regressão: a descrição dos grupos era dict de módulo, e o
        grupo de um comando aparecia na descrição do outro."""
        a = CommandInstance(_chat("um", "d"), _handler)
        b = CommandInstance(_chat("dois", "d"), _handler)

        a.group("alpha", "descrição de alpha").add("add", _add)
        b.group("beta", "descrição de beta").add("add", _add)

        assert a.definition.options[0].description == "descrição de alpha"
        assert b.definition.options[0].description == "descrição de beta"

    def test_sub_em_context_menu_e_erro(self) -> None:
        """USER/MESSAGE não têm estrutura — o alvo vem do clique."""
        inst = CommandInstance(
            CommandDefinition("menu", "", type=ApplicationCommandType.USER), _handler
        )
        with pytest.raises(CommandDefinitionError, match="só existe em CHAT_INPUT"):
            inst.sub("x", _add)

    def test_autocomplete_registra_por_opcao(self) -> None:
        inst = CommandInstance(_chat(), _handler)

        @inst.autocomplete("cor")
        async def _(inter: AutocompleteInteraction) -> None: ...

        assert "cor" in inst.autocomplete_handlers

    def test_autocomplete_duplicado_e_erro(self) -> None:
        """Dois autores brigando por uma opção — o perdedor não saberia
        qual deles perdeu."""
        inst = CommandInstance(_chat(), _handler)

        @inst.autocomplete("cor")
        async def _(inter: AutocompleteInteraction) -> None: ...

        with pytest.raises(CommandDefinitionError, match="já registrado"):

            @inst.autocomplete("cor")
            async def outro(inter: AutocompleteInteraction) -> None: ...

    def test_autocomplete_generico_por_default(self) -> None:
        inst = CommandInstance(_chat(), _handler)

        @inst.autocomplete()
        async def _(inter: AutocompleteInteraction) -> None: ...

        assert "*" in inst.autocomplete_handlers


# --------------------------------------------------------------------------
# CommandRegistry — 0011
# --------------------------------------------------------------------------


class TestRegistry:
    def test_chave_tem_tres_pontas(self) -> None:
        """Um menu USER chamado `ping` e o `/ping` são dois comandos.
        Com duas pontas o segundo seria recusado como duplicata."""
        reg = CommandRegistry()
        slash = CommandInstance(_chat("ping", "pong"), _handler)
        menu = CommandInstance(
            CommandDefinition("ping", "", type=ApplicationCommandType.USER), _handler
        )

        assert reg.register(slash) is slash
        assert reg.register(menu) is menu
        assert len(reg) == 2

    def test_escopos_distintos_nao_colidem(self) -> None:
        """O `K1` faz o mesmo nome valer por guild."""
        reg = CommandRegistry()
        global_ = CommandInstance(_chat(), _handler)
        guild = CommandInstance(_chat().com_escopo(42), _handler)

        reg.register(global_)
        reg.register(guild)

        assert len(reg) == 2
        assert reg.for_scope(None) == (global_,)
        assert reg.for_scope(42) == (guild,)

    def test_registro_identico_e_silencioso(self) -> None:
        """`bootstrap` + import direto do usuário é o caminho normal —
        derrubar por isso derrubaria o caso comum."""
        reg = CommandRegistry()
        a = CommandInstance(_chat(), _handler)
        b = CommandInstance(_chat(), _handler)

        assert reg.register(a) is a
        assert reg.register(b) is a

    def test_registro_conflitante_cita_os_dois_modulos(self) -> None:
        """Dois módulos brigando pelo mesmo nome é erro real — e sem os
        dois locais na mensagem, o usuário persegue o lugar errado."""
        reg = CommandRegistry()
        reg.register(CommandInstance(_chat("ping", "pong"), _handler))

        com_outra_desc = CommandInstance(_chat("ping", "outra coisa"), _handler)
        with pytest.raises(CommandDefinitionError) as info:
            reg.register(com_outra_desc)

        texto = str(info.value)
        assert "description" in texto
        assert "pong" in texto and "outra coisa" in texto

    def test_get_e_has(self) -> None:
        reg = CommandRegistry()
        inst = CommandInstance(_chat(), _handler)
        reg.register(inst)

        assert reg.get(ApplicationCommandType.CHAT_INPUT, "ping") is inst
        assert reg.has(ApplicationCommandType.CHAT_INPUT, "ping") is True
        assert reg.has(ApplicationCommandType.CHAT_INPUT, "nao") is False
        assert reg.get(ApplicationCommandType.CHAT_INPUT, "nao") is None

    def test_scopes_com_global_primeiro(self) -> None:
        """`None` primeiro porque é o que o `sync()` despacha primeiro —
        e o global é o que leva até 1 hora para propagar."""
        reg = CommandRegistry()
        reg.register(CommandInstance(_chat("a", "d").com_escopo(30), _handler))
        reg.register(CommandInstance(_chat("b", "d").com_escopo(10), _handler))
        reg.register(CommandInstance(_chat("c", "d"), _handler))

        assert reg.scopes() == (None, 10, 30)

    def test_instances_e_estavel(self) -> None:
        """Ordem estável entre execuções: o diff do `sync()` enxergaria
        movimentação como mudança."""
        reg = CommandRegistry()
        nomes = ["ze", "ana", "bia"]
        for n in nomes:
            reg.register(CommandInstance(_chat(n, "d"), _handler))

        primeira = [i.name for i in reg.instances()]
        segunda = [i.name for i in reg.instances()]

        assert primeira == segunda == sorted(nomes)

    def test_iteracao_e_len(self) -> None:
        reg = CommandRegistry()
        reg.register(CommandInstance(_chat("a", "d"), _handler))
        reg.register(CommandInstance(_chat("b", "d"), _handler))

        assert len(reg) == 2
        assert {i.name for i in reg} == {"a", "b"}
