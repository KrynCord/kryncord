"""`CommandSync` — `0018`.

O fio: **diff antes de enviar**. Um sync sem mudança faz `GET` e não
manda `PUT` — e é isso que faz o `verbose` dizer a verdade.

Nenhum teste aqui toca na rede: o `ApplicationsAPI` é um dublê.
"""

from __future__ import annotations

import pytest

from kryncord.commands import CommandDefinition, CommandInstance, CommandRegistry
from kryncord.commands.option import Option
from kryncord.commands.sync import CommandSync, SyncReport
from kryncord.enums import ApplicationCommandType
from kryncord.errors import DefinitionError
from kryncord.models.command import ApplicationCommand

APP_ID = 999


async def _handler(ctx: object = None) -> None:
    """responde pong"""


class ApiFalsa:
    """Dublê do `ApplicationsAPI`. Guarda o que recebeu."""

    def __init__(self, remotos: list[ApplicationCommand] | None = None) -> None:
        self.remotos = remotos or []
        self.puts: list[tuple[int | None, list[dict]]] = []
        self.gets: list[int | None] = []
        self.quebra: Exception | None = None

    async def me(self) -> dict:
        return {"id": str(APP_ID), "name": "teste"}

    async def list_commands(self, application_id, *, guild_id=None):
        self.gets.append(guild_id)
        if self.quebra is not None:
            raise self.quebra
        return [c for c in self.remotos if c.guild_id == guild_id]

    async def bulk_overwrite_commands(self, application_id, commands, *, guild_id=None):
        self.puts.append((guild_id, [dict(c) for c in commands]))
        if self.quebra is not None:
            raise self.quebra


def _remoto(nome: str, descricao: str = "responde pong", **kwargs) -> ApplicationCommand:
    return ApplicationCommand(
        id=1,
        application_id=APP_ID,
        name=nome,
        description=descricao,
        type=1,
        **kwargs,
    )


def _registro(*definicoes: CommandDefinition) -> tuple[CommandRegistry, CommandSync, ApiFalsa]:
    reg = CommandRegistry()
    for d in definicoes:
        reg.register(CommandInstance(d, _handler))
    api = ApiFalsa()
    return reg, CommandSync(reg, api), api


def _chat(nome: str = "ping", descricao: str = "responde pong", **kwargs) -> CommandDefinition:
    return CommandDefinition(name=nome, description=descricao, **kwargs)


# --------------------------------------------------------------------------
# Criação
# --------------------------------------------------------------------------


class TestCriacao:
    async def test_comando_novo_e_criado(self) -> None:
        _, sync, api = _registro(_chat())

        report = await sync.sync()

        assert report.created == ((None, "ping (CHAT_INPUT)"),)
        assert report.vazio is False
        assert len(api.puts) == 1
        assert api.puts[0][0] is None  # escopo global

    async def test_payload_enviado_e_o_da_definicao(self) -> None:
        _, sync, api = _registro(_chat())

        await sync.sync()

        assert api.puts[0][1] == [{"name": "ping", "description": "responde pong", "type": 1}]

    async def test_um_put_por_escopo(self) -> None:
        """Bulk por escopo: um `PUT` para o global, um para cada guild.
        `PATCH` por comando com rate limit global de 2/h seria fila de
        meia hora."""
        d_global = _chat("ping", "pong")
        d_guild = CommandDefinition("ping", "pong", scope=42)
        _, sync, api = _registro(d_global, d_guild)

        await sync.sync()

        assert [p[0] for p in api.puts] == [None, 42]
        assert api.gets == [None, 42]


# --------------------------------------------------------------------------
# Diff
# --------------------------------------------------------------------------


class TestDiff:
    async def test_identico_e_unchanged_sem_put(self) -> None:
        """O ponto todo: sem mudança, não manda nada. Sem isto, todo
        boot reenviaria a lista e o `verbose` mentiria."""
        _, sync, api = _registro(_chat())
        api.remotos = [_remoto("ping")]

        report = await sync.sync()

        assert report.unchanged == ((None, "ping (CHAT_INPUT)"),)
        assert report.vazio is True
        assert api.puts == []  # nenhum PUT

    async def test_required_ausente_no_remoto_nao_conta_como_mudanca(self) -> None:
        """O Discord omite `required` quando é falso; o payload local
        sempre manda. Sem a normalização, o diff diria "atualizado" para
        sempre — e o `verbose` mentiria a cada boot."""
        d = _chat(options=(Option.string("nome", "um nome", required=False),))
        _, sync, api = _registro(d)
        api.remotos = [
            _remoto(
                "ping",
                options=[{"name": "nome", "type": 3, "description": "um nome"}],
            )
        ]

        report = await sync.sync()

        assert report.vazio is True
        assert api.puts == []

    async def test_opcao_nova_e_updated(self) -> None:
        d = _chat(options=(Option.string("nome", "um nome"),))
        _, sync, api = _registro(d)
        api.remotos = [_remoto("ping")]

        report = await sync.sync()

        assert report.updated == ((None, "ping (CHAT_INPUT)"),)
        assert len(api.puts) == 1

    async def test_descricao_diferente_e_updated(self) -> None:
        _, sync, api = _registro(_chat(descricao="outra"))
        api.remotos = [_remoto("ping")]

        report = await sync.sync()

        assert report.updated == ((None, "ping (CHAT_INPUT)"),)

    async def test_remoto_sem_local_e_deleted(self) -> None:
        """Comando que saiu do código continua no Discord — e aparece
        pro usuário como comando que não faz nada. É por isso que o
        `PUT` bulk apaga.

        O escopo precisa existir localmente para ser visitado; sem
        nenhum comando registrado, o sync inteiro é abortado (ver
        `TestRegistroVazio`)."""
        _, sync, api = _registro(_chat("ping"))
        api.remotos = [_remoto("ping"), _remoto("velho")]

        report = await sync.sync()

        assert report.deleted == ((None, "velho (CHAT_INPUT)"),)
        # O PUT sai com o que restou — e é ele que apaga o órfão.
        assert len(api.puts) == 1
        assert [c["name"] for c in api.puts[0][1]] == ["ping"]

    async def test_menu_user_nao_colidiria_com_slash(self) -> None:
        """A chave tem `type` — um menu USER `ping` e o `/ping` são dois
        comandos, e o diff não os confunde."""
        slash = _chat("ping", "pong")
        menu = CommandDefinition("ping", "", type=ApplicationCommandType.USER)

        reg = CommandRegistry()
        reg.register(CommandInstance(slash, _handler))
        reg.register(CommandInstance(menu, _handler))
        api = ApiFalsa([_remoto("ping", "pong")])

        report = await CommandSync(reg, api).sync()

        assert report.created == ((None, "ping (USER)"),)
        assert report.unchanged == ((None, "ping (CHAT_INPUT)"),)


# --------------------------------------------------------------------------
# Dry-run
# --------------------------------------------------------------------------


class TestDryRun:
    async def test_apply_false_nao_manda_put(self) -> None:
        """Auditar o que mudaria sem rede — é a única forma."""
        _, sync, api = _registro(_chat())

        report = await sync.sync(apply=False)

        assert report.created == ((None, "ping (CHAT_INPUT)"),)
        assert report.aplicado is False
        assert api.puts == []

    async def test_apply_false_ainda_faz_get(self) -> None:
        """Sem o `GET` não há diff — e diff é o que o dry-run promete."""
        _, sync, api = _registro(_chat())
        api.remotos = [_remoto("ping")]

        report = await sync.sync(apply=False)

        assert report.vazio is True
        assert api.gets == [None]

    async def test_relatorio_identico_com_e_sem_apply(self) -> None:
        """Dry-run e aplicação real enxergam a mesma coisa."""
        d = _chat()
        _, sync_a, _ = _registro(d)
        _, sync_b, _ = _registro(d)

        com = await sync_a.sync(apply=True)
        sem = await sync_b.sync(apply=False)

        assert com.created == sem.created
        assert com.updated == sem.updated
        assert com.deleted == sem.deleted
        assert com.unchanged == sem.unchanged


# --------------------------------------------------------------------------
# Validação antes da requisição
# --------------------------------------------------------------------------


class TestValidacaoPrevia:
    async def test_grupo_sem_subcommand_derruba_antes_de_mandar(self) -> None:
        """O erro tem que sair antes da primeira requisição — mandar
        metade e depois falhar com 400 sem dizer qual, é o pior caso."""
        grupo_vazio = CommandDefinition(
            name="papel",
            description="gerencia",
            options=(Option.group("papel", "gerencia papeis"),),
        )
        reg = CommandRegistry()
        reg.register(CommandInstance(grupo_vazio, _handler))
        api = ApiFalsa()
        sync = CommandSync(reg, api)

        with pytest.raises(DefinitionError, match="grupo 'papel' sem subcommand"):
            await sync.sync()

        assert api.gets == []
        assert api.puts == []

    async def test_descricao_invalida_tambem_previa(self) -> None:
        _, sync, api = _registro(_chat(descricao=""))

        with pytest.raises(DefinitionError, match="exige description"):
            await sync.sync()

        assert api.gets == []


# --------------------------------------------------------------------------
# application_id
# --------------------------------------------------------------------------


class TestApplicationId:
    async def test_vem_de_me_e_e_cacheado(self) -> None:
        """Uma chamada só, para todos os escopos — buscar duas vezes é
        uma requisição a mais por boot."""
        d_global = _chat("ping", "pong")
        d_guild = CommandDefinition("ping", "pong", scope=42)
        _, sync, _api = _registro(d_global, d_guild)

        await sync.sync()

        # `gets` registra as listagens; o `me()` é uma chamada separada
        # e não aparece aqui. O ponto é que dois escopos não dobram o
        # application_id — é cacheado no objeto.
        assert sync._app_id == APP_ID

    async def test_sem_id_e_erro_claro(self) -> None:
        """Se o Discord não devolver `id`, não há como construir a URL.
        O erro tem que dizer isso, não 'KeyError'."""
        _, sync, _api = _registro(_chat())

        class ApiSemId(ApiFalsa):
            async def me(self):
                return {"name": "sem id"}

        sync = CommandSync(sync._registry, ApiSemId())

        with pytest.raises(ValueError, match="application_id"):
            await sync.sync()


# --------------------------------------------------------------------------
# Relatório
# --------------------------------------------------------------------------


class TestRelatorio:
    def test_vazio_com_zero_comandos(self) -> None:
        report = SyncReport()

        assert report.vazio is True
        assert report.mudancas == 0
        assert report.linhas() == []

    def test_mudancas_conta_os_tres(self) -> None:
        report = SyncReport(
            created=((None, "a"), (42, "b")),
            updated=((None, "c"),),
            deleted=((7, "d"),),
        )

        assert report.mudancas == 4
        assert report.vazio is False

    def test_linhas_mencionam_o_escopo(self) -> None:
        """Sem o escopo, "criado" não diz para onde foi — e o global
        leva até 1 hora para propagar, que é o dado que importa."""
        report = SyncReport(created=((None, "ping"), (42, "papel")))

        linhas = report.linhas()

        assert any("ping" in linha and "global" in linha for linha in linhas)
        assert any("papel" in linha and "guild 42" in linha for linha in linhas)

    def test_linhas_vazias_quando_nao_mudou(self) -> None:
        report = SyncReport(unchanged=((None, "ping"),))

        assert report.vazio is True
        assert report.linhas() == []


# --------------------------------------------------------------------------
# verbose
# --------------------------------------------------------------------------


class TestVerbose:
    async def test_verbose_com_mudanca(self, caplog) -> None:
        """`verbose` imprime as linhas do relatório. Independente de
        `load_logs`, que é do `bootstrap` — perguntas diferentes."""
        import logging

        _, sync, _ = _registro(_chat())

        with caplog.at_level(logging.INFO, logger="kryncord"):
            await sync.sync(verbose=True)

        assert any("criado" in r.message for r in caplog.records)

    async def test_verbose_sem_mudanca(self, caplog) -> None:
        import logging

        _, sync, api = _registro(_chat())
        api.remotos = [_remoto("ping")]

        with caplog.at_level(logging.INFO, logger="kryncord"):
            await sync.sync(verbose=True)

        assert any("nenhuma mudança" in r.message for r in caplog.records)

    async def test_sem_verbose_nao_imprime_as_linhas(self, caplog) -> None:
        """O resumo por escopo sai sempre — é informação de boot. O que
        `verbose` controla é o detalhe por comando."""
        import logging

        _, sync, _ = _registro(_chat())

        with caplog.at_level(logging.INFO, logger="kryncord"):
            await sync.sync()

        mensagens = [r.message for r in caplog.records]
        assert not any("[criado]" in m for m in mensagens)


class TestRegistroVazio:
    async def test_nao_manda_nada_e_avisa(self) -> None:
        """Registro vazio é quase sempre bug, não intenção — e
        sincronizar apagaria tudo que o bot tem no Discord.

        Distinto de "um escopo com zero comandos", que apaga o remoto:
        esse é o comando órfão."""
        reg = CommandRegistry()
        api = ApiFalsa([_remoto("ping")])
        sync = CommandSync(reg, api)

        report = await sync.sync()

        assert report.vazio is True
        assert api.gets == []
        assert api.puts == []

    async def test_aviso_menciona_a_saida(self, caplog) -> None:
        """Sem apontar a saída, o usuário fica sem saber o que fazer —
        e vai tentar o sync de novo achando que falhou."""
        import logging

        reg = CommandRegistry()
        api = ApiFalsa()

        with caplog.at_level(logging.WARNING, logger="kryncord"):
            await CommandSync(reg, api).sync()

        avisos = [r.message for r in caplog.records]
        assert any("nenhum comando registrado" in m for m in avisos)
        assert any("delete_command" in m for m in avisos)

    async def test_apply_false_tambem_aborta(self) -> None:
        """Dry-run sem escopos não tem o que calcular."""
        reg = CommandRegistry()
        api = ApiFalsa([_remoto("ping")])

        report = await CommandSync(reg, api).sync(apply=False)

        assert report.aplicado is False
        assert api.gets == []
