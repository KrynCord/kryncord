"""`Permissions` e `parse_permissions`.

O ponto que mais importa aqui: `bool` é subclasse de `int` em Python.
Sem a checagem na frente, `parse_permissions(True)` viraria
`ADMINISTRATOR` — um `True` esquecido virando permissão total, em
silêncio.
"""

from __future__ import annotations

import pytest

from kryncord.errors import DefinitionError
from kryncord.permissions import Permissions, parse_permissions, parse_permissions_list


class TestParse:
    def test_nome(self) -> None:
        assert parse_permissions("MANAGE_GUILD") is Permissions.MANAGE_GUILD

    def test_nome_maiusculo_e_com_espaco(self) -> None:
        """`"manage guild"` e `"Manage-Guild"` são o mesmo nome. O
        Discord escreve em caixa alta com underscore, mas quem digita
        no decorator não vai lembrar disso toda vez."""
        assert parse_permissions("manage guild") is Permissions.MANAGE_GUILD
        assert parse_permissions("manage-guild") is Permissions.MANAGE_GUILD

    def test_flag_passa_direto(self) -> None:
        """Idempotente: já convertido não converte de novo."""
        assert parse_permissions(Permissions.KICK_MEMBERS) is Permissions.KICK_MEMBERS

    def test_numero(self) -> None:
        assert parse_permissions(1 << 5) is Permissions.MANAGE_GUILD

    def test_bool_e_rejeitado(self) -> None:
        """A checagem vem **antes** da de `int` — sem isto, `True` é
        `ADMINISTRATOR`. É o silêncio mais caro que este módulo poderia
        produzir."""
        with pytest.raises(DefinitionError, match="não é uma permissão"):
            parse_permissions(True)

        with pytest.raises(DefinitionError):
            parse_permissions(False)

    def test_nome_desconhecido_sugere(self) -> None:
        """Sugestão só quando a similaridade é alta — sugerir a
        qualquer custo é pior, porque o usuário confia no texto."""
        with pytest.raises(DefinitionError, match="MANAGE_GUILDS") as info:
            parse_permissions("MANAGE_GUILDS")

        assert "quis dizer" in str(info.value)

    def test_nome_desconhecido_sem_sugestao(self) -> None:
        """Corte em 0.6: um nome totalmente diferente não ganha dica."""
        with pytest.raises(DefinitionError, match="Zzzz") as info:
            parse_permissions("Zzzz")

        assert "quis dizer" not in str(info.value)

    def test_tipo_incompativel(self) -> None:
        with pytest.raises(DefinitionError, match="list"):
            parse_permissions([1, 2, 3], where="campo")

    def test_where_entra_na_mensagem(self) -> None:
        """O `where` é o que faz o erro apontar o campo certo — sem
        ele, três campos iguais na tela e nenhuma pista de qual."""
        with pytest.raises(DefinitionError, match=r"meu\.campo"):
            parse_permissions("NADA", where="meu.campo")


class TestParseList:
    def test_none_e_sem_restricao(self) -> None:
        """`None` não é `Permissions(0)`. Fundir os dois abriria o
        comando para todo mundo quando o autor quis fechar para staff."""
        assert parse_permissions_list(None) is None

    def test_item_solo(self) -> None:
        assert parse_permissions_list("KICK_MEMBERS") is Permissions.KICK_MEMBERS

    def test_sequencia_combina(self) -> None:
        resultado = parse_permissions_list(["KICK_MEMBERS", "BAN_MEMBERS", 1 << 5])

        assert resultado is (
            Permissions.KICK_MEMBERS | Permissions.BAN_MEMBERS | Permissions.MANAGE_GUILD
        )

    def test_bool_na_sequencia_tambem_rejeitado(self) -> None:
        with pytest.raises(DefinitionError):
            parse_permissions_list([True])

    def test_bool_solo_rejeitado(self) -> None:
        with pytest.raises(DefinitionError):
            parse_permissions_list(True)


class TestPermissions:
    def test_all_cobre_os_bits_conhecidos(self) -> None:
        """`Permissions.all()` é o atalho de "qualquer uma" — e tem
        que cobrir todos os membros declarados, senão o `|` perde bit."""
        todas = Permissions.all()

        for membro in Permissions:
            assert todas & membro.value, f"{membro.name} sumiu de all()"

    def test_all_nao_e_zero(self) -> None:
        assert int(Permissions.all()) != 0

    def test_bits_sao_unicos(self) -> None:
        """Bit repetido em dois membros faria `Permissions.A | B` virar
        um só — e a validação passaria errada sem nunca reclamar."""
        valores = [m.value for m in Permissions]
        assert len(valores) == len(set(valores))

    def test_bits_sao_potencias_de_dois(self) -> None:
        """O mesmo motivo: bitmask não aceita valor composto."""
        for membro in Permissions:
            v = membro.value
            assert v > 0 and (v & (v - 1)) == 0, f"{membro.name} = {v} não é bit"


class TestIntegracao:
    def test_command_options_aceita_as_tres_formas(self) -> None:
        """O `K10`/`0010` decide que `default_member_permissions`
        aceita qualquer forma — e as três têm que resolver para o
        mesmo valor, ou o usuário escolhe a forma e descobre que uma
        delas não funciona."""
        from kryncord.config import CommandOptions

        por_nome = CommandOptions(default_member_permissions="MANAGE_GUILD")
        por_numero = CommandOptions(default_member_permissions=1 << 5)
        por_flag = CommandOptions(default_member_permissions=Permissions.MANAGE_GUILD)
        por_lista = CommandOptions(default_member_permissions=["MANAGE_GUILD"])

        resolvidos = {
            por_nome.default_member_permissions_resolved,
            por_numero.default_member_permissions_resolved,
            por_flag.default_member_permissions_resolved,
            por_lista.default_member_permissions_resolved,
        }

        assert resolvidos == {Permissions.MANAGE_GUILD}

    def test_command_options_none_continua_none(self) -> None:
        from kryncord.config import CommandOptions

        assert CommandOptions().default_member_permissions_resolved is None

    def test_erro_aparece_na_construcao_nao_no_sync(self) -> None:
        """O erro tem que sair na linha do `Config(...)`, não depois
        de montar e enviar o comando."""
        from kryncord.config import CommandOptions

        with pytest.raises(DefinitionError, match="default_member_permissions"):
            CommandOptions(default_member_permissions="MANAGE_GUILDZ")
