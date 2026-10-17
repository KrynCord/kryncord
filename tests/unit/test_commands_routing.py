"""Testes do Bloco 8 — escopo declarado, cadeia de níveis e roteamento.

Quatro perguntas separadas, e elas têm respostas diferentes:

| Pergunta | Onde |
|---|---|
| O comando vai para qual guild? | `_escopos_de` (`0028` §1) |
| Quem recebe o valor do pai? | `_cascata` / `_injeta` (`0026` §3) |
| Que ramo a interação toma? | `dispatch_interaction` (`0026` §4) |
| O roteamento vem antes de `@event`? | `Client.dispatch` (`0025` §4) |

Nenhum teste toca rede: o `api` é um duplo que só registra chamadas, e o
`Client` do último bloco nunca recebe `start()`. O registry é novo em
cada caso — registries compartilhados entre testes são contaminação que
aparece como falha num outro teste qualquer (`K12`).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from kryncord import AutocompleteInteraction, CommandInteraction, command, create_command, event
from kryncord.client import Client
from kryncord.commands.dispatch import dispatch_application_command, instancia_de
from kryncord.commands.registry import CommandRegistry
from kryncord.config import CommandOptions, Config, EventOptions, ResponderOptions
from kryncord.enums import ApplicationCommandType, InteractionType, ResponderType
from kryncord.errors import CommandDefinitionError, DispatchError, HandlerSignatureError
from kryncord.intents import Intents
from kryncord.interactions.dispatch import dispatch_interaction
from kryncord.models.interaction import Interaction
from kryncord.registry import Registry
from tests.unit.test_api import make_api, no_content

CHAT = ApplicationCommandType.CHAT_INPUT


# ---------------------------------------------------------------------------
# Duplos e montagem
# ---------------------------------------------------------------------------


class _ApiFalsa:
    """Registra o que foi perguntado, sem perguntar a ninguém."""

    __slots__ = ("autocompletes", "callbacks")

    def __init__(self) -> None:
        self.autocompletes: list[Any] = []
        self.callbacks: list[Any] = []

    async def autocomplete(self, interaction: Any, choices: Any) -> None:
        self.autocompletes.append(choices)

    async def callback(self, *args: Any) -> None:
        self.callbacks.append(args)


def cria(nome: str = "ping", **kwargs: Any) -> tuple[CommandRegistry, Any]:
    reg = CommandRegistry()
    kwargs.setdefault("description", "Descrição do comando")
    return reg, create_command(name=nome, registry=reg, **kwargs)


def interacao(
    nome: str,
    *,
    tipo: int = InteractionType.APPLICATION_COMMAND,
    guild_id: int | None = None,
    options: list[Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> Interaction:
    """Um payload de interação que `Interaction.from_payload` aceita.

    `id`, `type` e `token` são o mínimo que o modelo exige: sem eles ele
    devolve `None`, e o teste falharia por motivo errado — o
    roteamento "falharia" no parse e não no roteamento.
    """
    data: dict[str, Any] = {"name": nome}
    if options is not None:
        data["options"] = options
    if extra:
        data.update(extra)

    bruto: dict[str, Any] = {
        "id": "111111111111111111",
        "application_id": "222222222222222222",
        "type": int(tipo),
        "token": "tok-de-teste",
        "version": 1,
        "channel_id": "333333333333333333",
        "data": data,
    }
    if guild_id is not None:
        bruto["guild_id"] = str(guild_id)

    achado = Interaction.from_payload(bruto)
    assert achado is not None, "o fixture de payload tem que ser aceito pelo modelo"
    return achado


# ==========================================================================
# Tabela de escopo (0028 §1)
# ==========================================================================


class TestTabelaDeEscopo:
    def test_nada_declarado_fica_adiado(self) -> None:
        """`deferido` é `True` só quando o decorator não disse nada —
        é o caso em que o escopo vem do `Config` (`0028`)."""
        _reg, inst = cria("meu")

        assert inst.deferido is True
        assert inst.escopos == (None,)

    def test_is_global_true_e_global_nao_adiado(self) -> None:
        reg, inst = cria("meu", is_global=True)

        assert inst.deferido is False
        assert inst.escopos == (None,)
        assert reg.get(CHAT, "meu", None) is inst

    def test_guild_um_escopo(self) -> None:
        reg, inst = cria("meu", guild=123)

        assert inst.deferido is False
        assert inst.escopos == (123,)
        assert reg.get(CHAT, "meu", 123) is inst
        assert reg.get(CHAT, "meu", None) is None

    def test_guild_sequencia_duas_chaves_mesma_instancia(self) -> None:
        """Duas chaves, **um** objeto. Instância por escopo, com
        `_rebuild` em cascata, faria `.sub()` num escopo afetar só o
        primeiro — e a sincronia se manteria só enquanto ninguém
        esquecesse (`0026` §2)."""
        reg, inst = cria("meu", guild=(1, 2))

        assert inst.escopos == (1, 2)
        assert reg.get(CHAT, "meu", 1) is inst
        assert reg.get(CHAT, "meu", 2) is inst

    def test_is_global_false_sem_guild_e_erro(self) -> None:
        """O comando não iria a lugar nenhum, e o `sync` o mandaria
        para a rota global em silêncio."""
        with pytest.raises(CommandDefinitionError, match="guild"):
            cria("meu", is_global=False)

    def test_dois_sinais_juntos_e_erro(self) -> None:
        with pytest.raises(CommandDefinitionError, match="juntos"):
            cria("meu", is_global=True, guild=1)

    def test_bool_como_guild_e_erro(self) -> None:
        """`true` é JSON quebrado, não a guild 1 — e a coerção
        silenciosa mandaria o comando para o servidor errado."""
        with pytest.raises(CommandDefinitionError, match="bool"):
            cria("meu", guild=True)  # type: ignore[arg-type]

    def test_guild_vazio_e_erro(self) -> None:
        with pytest.raises(CommandDefinitionError, match="vazio"):
            cria("meu", guild=())

    def test_erro_aparece_na_definicao_nao_no_clique(self) -> None:
        """Descobrir no clique seria descobrir depois do bot publicado,
        e a mensagem do Discord não aponta para arquivo nenhum."""
        with pytest.raises(CommandDefinitionError) as erro:
            cria("meu", is_global=False)
        assert "meu" in str(erro.value)

    def test_decorator_devolve_a_funcao_e_registra(self) -> None:
        reg = CommandRegistry()

        @command(name="ping", description="Ping", registry=reg)
        async def ping(ctx: CommandInteraction) -> None: ...

        inst = reg.get(CHAT, "ping", None)
        assert inst is not None
        assert inst.handler is ping
        assert ping.__name__ == "ping"

    def test_decorator_sem_parametro_e_erro(self) -> None:
        """`async def ping()` registraria um comando sem ninguém para
        receber a interação — o registro falha na importação
        (`HandlerSignatureError`, `0031`), não a cada clique com o
        `TypeError` que a mensagem do Discord não explica."""
        reg = CommandRegistry()

        with pytest.raises(HandlerSignatureError, match="sem parâmetros"):

            @command(name="ping", description="Ping", registry=reg)
            async def ping() -> None: ...

    def test_handler_sincrono_e_erro(self) -> None:
        reg = CommandRegistry()

        with pytest.raises(TypeError, match="async def"):

            @command(name="ping", description="Ping", registry=reg)
            def ping(ctx: CommandInteraction) -> None: ...  # type: ignore[misc]


# ==========================================================================
# reescopiar (0028)
# ==========================================================================


class TestReescopiar:
    def test_vazio_e_no_op(self) -> None:
        """`()` significa "padrão é global", e o adiado já está no
        global — é o que faz todo bot que nunca mexeu em `guilds`
        continuar igual."""
        reg, inst = cria("meu")

        reg.reescopiar(())

        assert inst.escopos == (None,)
        assert inst.deferido is True
        assert reg.get(CHAT, "meu", None) is inst

    def test_move_adiado_para_os_escopos_do_config(self) -> None:
        reg, inst = cria("meu")

        reg.reescopiar((7, 8))

        assert inst.escopos == (7, 8)
        assert inst.deferido is False
        assert reg.get(CHAT, "meu", 7) is inst
        assert reg.get(CHAT, "meu", 8) is inst
        assert reg.get(CHAT, "meu", None) is None

    def test_explícitos_não_mexem(self) -> None:
        """`guild=` na mão é decisão do autor, não default — o
        `reescopiar` só pega o que ficou adiado."""
        reg, inst = cria("meu", guild=5)

        reg.reescopiar((7,))

        assert inst.escopos == (5,)
        assert reg.get(CHAT, "meu", 5) is inst
        assert reg.get(CHAT, "meu", 7) is None

    def test_os_dois_no_mesmo_registry(self) -> None:
        """Os dois casos juntos é onde o bug apareceria: mover os dois
        faria o explícito sumir do escopo que o autor escolheu."""
        reg = CommandRegistry()
        adiado = create_command(name="adiado", description="d", registry=reg)
        explicito = create_command(name="expl", description="d", registry=reg, guild=5)

        reg.reescopiar((9,))

        assert adiado.escopos == (9,)
        assert reg.get(CHAT, "adiado", 9) is adiado
        assert explicito.escopos == (5,)
        assert reg.get(CHAT, "expl", 5) is explicito
        assert reg.get(CHAT, "expl", 9) is None


# ==========================================================================
# Cadeia de níveis (0026 §3)
# ==========================================================================


class TestCadeia:
    async def test_raiz_devolve_valor_para_o_sub(self) -> None:
        """O ponto da ideia 04 §4: o pai calcula, o filho consome, e os
        dois estão no mesmo dispatch."""
        reg, inst = cria("loja")

        @inst
        async def raiz(ctx: CommandInteraction) -> str:
            return "saldo=10"

        recebido: list[str] = []

        async def ver(ctx: CommandInteraction, valor: str) -> None:
            recebido.append(valor)

        inst.sub("ver", ver)

        ok = await dispatch_application_command(
            interacao("loja", options=[{"type": 1, "name": "ver"}]),
            _ApiFalsa(),
            registry=reg,
        )

        assert ok is True
        assert recebido == ["saldo=10"]

    async def test_raiz_sem_handler_passa_none(self) -> None:
        """O `run` da raiz é opcional (ideia 04 §6) — o caso da âncora
        `create_command(name="store")` com os handlers nos filhos."""
        reg, inst = cria("loja")

        recebido: list[Any] = []

        async def ver(ctx: CommandInteraction, valor: Any) -> None:
            recebido.append(valor)

        inst.sub("ver", ver)

        await dispatch_application_command(
            interacao("loja", options=[{"type": 1, "name": "ver"}]),
            _ApiFalsa(),
            registry=reg,
        )

        assert recebido == [None]

    async def test_sub_sem_parametro_descarta_o_valor(self) -> None:
        """O filho escolhe não participar, e isso não é erro — é a
        terceira linha da tabela do `0026` §3."""
        reg, inst = cria("loja")

        @inst
        async def raiz(ctx: CommandInteraction) -> str:
            return "não quero isso"

        chamou: list[str] = []

        async def ver(ctx: CommandInteraction) -> None:
            chamou.append("sim")

        inst.sub("ver", ver)

        await dispatch_application_command(
            interacao("loja", options=[{"type": 1, "name": "ver"}]),
            _ApiFalsa(),
            registry=reg,
        )

        assert chamou == ["sim"]

    async def test_sub_de_tipo_errado_e_dispatch_error(self) -> None:
        """Anotar `int` onde a cadeia entrega `str` é erro de
        declaração, e o `DispatchError` diz o quê e o quê."""
        reg, inst = cria("loja")

        @inst
        async def raiz(ctx: CommandInteraction) -> str:
            return "texto"

        async def ver(ctx: CommandInteraction, valor: int) -> None: ...

        inst.sub("ver", ver)

        erros: list[BaseException] = []

        async def capta(ctx: Any, exc: BaseException) -> None:
            erros.append(exc)

        ok = await dispatch_application_command(
            interacao("loja", options=[{"type": 1, "name": "ver"}]),
            _ApiFalsa(),
            registry=reg,
            on_error=capta,
        )

        #: A cadeia foi **atendida** — devolver `False` faria o chamador
        #: disparar o `on_not_found` em cima de uma falha, e o usuário
        #: veria "algo deu errado" duas vezes.
        assert ok is True
        assert len(erros) == 1
        assert isinstance(erros[0], DispatchError)
        assert "anotava" in str(erros[0])

    async def test_uniao_none_aceita_none(self) -> None:
        """`T | None` + `None` passa — é o caso de um pai que não
        devolveu valor nenhum e o filho sabia disso."""
        reg, inst = cria("loja")

        recebido: list[Any] = []

        async def ver(ctx: CommandInteraction, valor: str | None) -> None:
            recebido.append(valor)

        inst.sub("ver", ver)

        await dispatch_application_command(
            interacao("loja", options=[{"type": 1, "name": "ver"}]),
            _ApiFalsa(),
            registry=reg,
        )

        assert recebido == [None]

    async def test_varargs_aceita_qualquer(self) -> None:
        """`K9`: quem escreveu `*args` disse que não quer número nenhum."""
        reg, inst = cria("loja")

        @inst
        async def raiz(ctx: CommandInteraction) -> int:
            return 42

        recebido: list[Any] = []

        async def ver(ctx: CommandInteraction, *args: Any) -> None:
            recebido.append(args)

        inst.sub("ver", ver)

        await dispatch_application_command(
            interacao("loja", options=[{"type": 1, "name": "ver"}]),
            _ApiFalsa(),
            registry=reg,
        )

        assert recebido == [(42,)]

    async def test_sem_anotacao_passa_como_esta(self) -> None:
        """A anotação do valor é ganho de editor, não contrato de
        runtime (`0031` só exige a do primeiro parâmetro)."""
        reg, inst = cria("loja")

        @inst
        async def raiz(ctx: CommandInteraction) -> list[int]:
            return [1, 2]

        recebido: list[Any] = []

        async def ver(ctx: CommandInteraction, valor) -> None:
            recebido.append(valor)

        inst.sub("ver", ver)

        await dispatch_application_command(
            interacao("loja", options=[{"type": 1, "name": "ver"}]),
            _ApiFalsa(),
            registry=reg,
        )

        assert recebido == [[1, 2]]

    async def test_grupo_com_sub_registrado(self) -> None:
        """`raiz → grupo → sub` é uma cadeia de três, não de dois, e o
        valor muda de mão a cada nível."""
        reg, inst = cria("papel")

        @inst
        async def raiz(ctx: CommandInteraction) -> str:
            return "membro"

        chamou: list[Any] = []

        async def no_grupo(ctx: CommandInteraction, valor: str) -> str:
            chamou.append(("grupo", valor))
            return valor.upper()

        async def dar(ctx: CommandInteraction, valor: str) -> None:
            chamou.append(("sub", valor))

        # `.handler()` devolve o próprio handler — ele também é
        # decorator (`@grupo.handler`) — então não se encadeia nele.
        grupo = inst.group("add")
        grupo.handler(no_grupo)
        grupo.add("dar", dar)

        await dispatch_application_command(
            interacao(
                "papel",
                options=[{"type": 2, "name": "add", "options": [{"type": 1, "name": "dar"}]}],
            ),
            _ApiFalsa(),
            registry=reg,
        )

        assert chamou == [("grupo", "membro"), ("sub", "MEMBRO")]

    async def test_grupo_sem_handler_vai_direto_ao_sub(self) -> None:
        """Um grupo que existe só para organizar a árvore no Discord:
        o valor do pai continua andando (`0026` §3)."""
        reg, inst = cria("papel")

        @inst
        async def raiz(ctx: CommandInteraction) -> str:
            return "membro"

        chamou: list[Any] = []

        async def dar(ctx: CommandInteraction, valor: str) -> None:
            chamou.append(valor)

        inst.group("add").add("dar", dar)

        await dispatch_application_command(
            interacao(
                "papel",
                options=[{"type": 2, "name": "add", "options": [{"type": 1, "name": "dar"}]}],
            ),
            _ApiFalsa(),
            registry=reg,
        )

        assert chamou == ["membro"]

    async def test_sub_nao_registrado_e_dispatch_error(self) -> None:
        """Registro e payload divergiram — é erro de sincronia, e a
        mensagem manda rodar o `sync` de novo."""
        reg, inst = cria("loja")

        @inst
        async def raiz(ctx: CommandInteraction) -> None:
            return None

        erros: list[BaseException] = []

        async def capta(ctx: Any, exc: BaseException) -> None:
            erros.append(exc)

        await dispatch_application_command(
            interacao("loja", options=[{"type": 1, "name": "fantasma"}]),
            _ApiFalsa(),
            registry=reg,
            on_error=capta,
        )

        assert len(erros) == 1
        assert isinstance(erros[0], DispatchError)
        assert "sync" in str(erros[0])

    async def test_sub_de_outro_tipo_de_option_nao_engana(self) -> None:
        """Uma opção comum não é subcomando — o `_caminho` só olha o
        primeiro item, e um `type=3` não abre cadeia nenhuma."""
        reg, inst = cria("loja")

        @inst
        async def raiz(ctx: CommandInteraction) -> None:
            chamou.append("raiz")

        chamou: list[str] = []

        await dispatch_application_command(
            interacao("loja", options=[{"type": 3, "name": "busca", "value": "x"}]),
            _ApiFalsa(),
            registry=reg,
        )

        assert chamou == ["raiz"]


# ==========================================================================
# dispatch_application_command
# ==========================================================================


class TestDispatchApplicationCommand:
    async def test_comando_simples_roda(self) -> None:
        reg, inst = cria("ping")

        rodou: list[Any] = []

        @inst
        async def ping(ctx: CommandInteraction) -> None:
            rodou.append(ctx)

        ok = await dispatch_application_command(interacao("ping"), _ApiFalsa(), registry=reg)

        assert ok is True
        assert len(rodou) == 1

    async def test_comando_inexistente_false_e_on_not_found(self) -> None:
        reg = CommandRegistry()
        achados: list[Any] = []

        async def nada(ctx: Any) -> None:
            achados.append(ctx)

        ok = await dispatch_application_command(
            interacao("fantasma"),
            _ApiFalsa(),
            registry=reg,
            on_not_found=nada,
        )

        assert ok is False
        assert len(achados) == 1

    async def test_payload_sem_name_false(self) -> None:
        """Sem `name` não há para onde rotear — e não é erro nosso."""
        bruto = {"id": "1", "type": 2, "token": "t"}
        inter = Interaction.from_payload(bruto)
        assert inter is not None

        ok = await dispatch_application_command(inter, _ApiFalsa(), registry=CommandRegistry())

        assert ok is False

    async def test_excecao_true_e_on_error(self) -> None:
        reg, inst = cria("ping")

        @inst
        async def ping(ctx: CommandInteraction) -> None:
            raise RuntimeError("boom")

        erros: list[BaseException] = []

        async def capta(ctx: Any, exc: BaseException) -> None:
            erros.append(exc)

        ok = await dispatch_application_command(
            interacao("ping"), _ApiFalsa(), registry=reg, on_error=capta
        )

        assert ok is True
        assert len(erros) == 1
        assert isinstance(erros[0], RuntimeError)

    async def test_block_true_e_on_error_nao_roda(self) -> None:
        """Quem chamou `block()` respondeu ali — bloqueio é tratamento
        (`0017`), não falha, e o `on_error` não pode rodar por cima."""
        reg, inst = cria("ping")

        @inst
        async def ping(ctx: CommandInteraction) -> None: ...

        erros: list[BaseException] = []

        async def capta(ctx: Any, exc: BaseException) -> None:
            erros.append(exc)

        async def para(ctx: Any, block: Any) -> None:
            block()

        ok = await dispatch_application_command(
            interacao("ping"),
            _ApiFalsa(),
            registry=reg,
            middleware=[para],
            on_error=capta,
        )

        assert ok is True
        assert erros == []

    async def test_middleware_global_roda_antes(self) -> None:
        reg, inst = cria("ping")
        ordem: list[str] = []

        @inst
        async def ping(ctx: CommandInteraction) -> None:
            ordem.append("handler")

        async def antes(ctx: Any, block: Any) -> None:
            ordem.append("middleware")

        await dispatch_application_command(
            interacao("ping"),
            _ApiFalsa(),
            registry=reg,
            middleware=[antes],
        )

        assert ordem == ["middleware", "handler"]

    async def test_middleware_do_comando_tambem_roda(self) -> None:
        """A cadeia é `(*global, *do_comando)` — as duas convivem."""
        reg = CommandRegistry()
        ordem: list[str] = []

        async def global_(ctx: Any, block: Any) -> None:
            ordem.append("global")

        async def local(ctx: Any, block: Any) -> None:
            ordem.append("local")

        inst = create_command(
            name="ping",
            description="Ping",
            registry=reg,
            middleware=local,
        )

        @inst
        async def ping(ctx: CommandInteraction) -> None:
            ordem.append("handler")

        await dispatch_application_command(
            interacao("ping"),
            _ApiFalsa(),
            registry=reg,
            middleware=[global_],
        )

        assert ordem == ["global", "local", "handler"]

    async def test_state_e_compartilhado_com_o_event(self) -> None:
        """O `0026` §D6: o mesmo dicionário para a middleware do
        comando, o handler e o `@event("interaction_create")`."""
        reg, inst = cria("ping")

        @inst
        async def ping(ctx: CommandInteraction) -> None:
            ctx.state["chave"] = "do-comando"

        compartilhado: dict[str, Any] = {}
        await dispatch_application_command(
            interacao("ping"),
            _ApiFalsa(),
            registry=reg,
            state=compartilhado,
        )

        assert compartilhado == {"chave": "do-comando"}

    async def test_comando_global_invocado_na_guild(self) -> None:
        """A segunda tentativa do `instancia_de`: a chave do global é
        `(tipo, nome, None)`, e o payload traz `guild_id` — sem o
        fallback todo comando global pararia de funcionar no único
        lugar onde alguém consegue clicar nele."""
        reg, inst = cria("ping", is_global=True)

        assert instancia_de(reg, interacao("ping", guild_id=123)) is inst

    async def test_comando_de_guild_nao_acha_em_outra_guild(self) -> None:
        reg, inst = cria("ping", guild=123)

        assert instancia_de(reg, interacao("ping", guild_id=456)) is None
        assert instancia_de(reg, interacao("ping", guild_id=123)) is inst


# ==========================================================================
# on_error por comando (0030 §1)
# ==========================================================================


class TestOnErrorPorComando:
    async def test_o_do_comando_vence_o_do_options(self) -> None:
        """Declarado no comando é decisão do autor; o global
        sobrescrevê-lo silenciosamente seria a prioridade invertida da
        middleware local sobre a global (`0017`)."""
        reg = CommandRegistry()
        rodou: list[str] = []

        async def global_(ctx: Any, exc: BaseException) -> None:
            rodou.append("options")

        async def local(ctx: Any, exc: BaseException) -> None:
            rodou.append("comando")

        inst = create_command(name="ping", description="Ping", registry=reg, on_error=local)

        @inst
        async def ping(ctx: CommandInteraction) -> None:
            raise RuntimeError("boom")

        await dispatch_application_command(
            interacao("ping"), _ApiFalsa(), registry=reg, on_error=global_
        )

        assert rodou == ["comando"]

    async def test_sem_declarar_herda_o_do_options(self) -> None:
        reg, inst = cria("ping")
        rodou: list[str] = []

        async def global_(ctx: Any, exc: BaseException) -> None:
            rodou.append("options")

        @inst
        async def ping(ctx: CommandInteraction) -> None:
            raise RuntimeError("boom")

        await dispatch_application_command(
            interacao("ping"), _ApiFalsa(), registry=reg, on_error=global_
        )

        assert rodou == ["options"]

    def test_on_not_found_nao_existe_no_decorator(self) -> None:
        """Ele nunca funcionou: `dispatch_application_command` só
        chega ao `on_not_found` quando a instância não existe, e aí
        não há de onde lê-lo. Parâmetro que parece funcionar e não
        funciona é pior que parâmetro inexistente (`0028`)."""
        with pytest.raises(TypeError, match="on_not_found"):
            create_command(
                name="ping",
                description="Ping",
                registry=CommandRegistry(),
                on_not_found=lambda ctx: None,  # type: ignore[call-arg]
            )

    def test_instancia_nao_tem_on_not_found(self) -> None:
        _reg, inst = cria("meu")

        assert not hasattr(inst, "on_not_found")


# ==========================================================================
# dispatch_interaction — os quatro ramos (0026 §4)
# ==========================================================================


def _registro_com(botao: bool = True) -> tuple[Registry, dict[str, Any]]:
    reg = Registry()
    registrou: dict[str, Any] = {}

    if botao:

        async def responder(ctx: Any) -> None:
            registrou["responder"] = ctx

        reg.responders.register(
            "/ping",
            responder,
            types=(ResponderType.BUTTON, ResponderType.MODAL_SUBMIT),
        )

    inst = create_command(name="ping", description="Ping", registry=reg.commands)

    @inst
    async def ping(ctx: CommandInteraction) -> None:
        registrou["comando"] = ctx

    return reg, registrou


class TestQuatroRamos:
    async def test_application_command_vai_para_o_comando(self) -> None:
        reg, registrou = _registro_com()

        ok = await dispatch_interaction(
            {"id": "1", "type": 2, "token": "t", "data": {"name": "ping"}},
            _ApiFalsa(),
            registry=reg,
        )

        assert ok is True
        assert "comando" in registrou
        assert "responder" not in registrou

    async def test_message_component_vai_para_o_responder(self) -> None:
        reg, registrou = _registro_com()

        ok = await dispatch_interaction(
            {
                "id": "1",
                "type": 3,
                "token": "t",
                "data": {"custom_id": "/ping", "component_type": 2},
            },
            _ApiFalsa(),
            registry=reg,
        )

        assert ok is True
        assert "responder" in registrou
        assert "comando" not in registrou

    async def test_modal_submit_vai_para_o_mesmo_responder(self) -> None:
        """`MESSAGE_COMPONENT` e `MODAL_SUBMIT` caem no mesmo despacho:
        a diferença entre os dois já está no `ResponderType` que o
        registro guarda."""
        reg, registrou = _registro_com()

        ok = await dispatch_interaction(
            {"id": "1", "type": 5, "token": "t", "data": {"custom_id": "/ping"}},
            _ApiFalsa(),
            registry=reg,
        )

        assert ok is True
        assert "responder" in registrou

    async def test_autocomplete_vai_para_o_autocomplete(self) -> None:
        reg, registrou = _registro_com(botao=False)
        api = _ApiFalsa()
        inst = reg.commands.get(CHAT, "ping", None)
        assert inst is not None

        @inst.autocomplete()
        async def sugere(ctx: AutocompleteInteraction) -> list[dict[str, Any]]:
            registrou["autocomplete"] = ctx
            #: `(nome, valor)`, dict e `Choice` são as três formas —
            #: uma string crua não é escolha, é um item inválido, e o
            #: `normalize_choices` a descarta em DEBUG.
            return [{"name": "pinguim", "value": "ping"}]

        ok = await dispatch_interaction(
            {
                "id": "1",
                "type": 4,
                "token": "t",
                "data": {
                    "name": "ping",
                    "options": [{"type": 3, "name": "q", "value": "pi", "focused": True}],
                },
            },
            api,
            registry=reg,
        )

        assert ok is True
        assert "autocomplete" in registrou
        #: O comando em si **não** roda num autocomplete — o Discord
        #: quer a lista, não a execução.
        assert "comando" not in registrou
        assert api.autocompletes == [[{"name": "pinguim", "value": "ping"}]]

    async def test_payload_malformado_false_sem_erro(self) -> None:
        """O Discord manda o que manda, e punir a conexão inteira por
        um campo ausente seria perder os próximos eventos."""
        reg, _ = _registro_com()

        ok = await dispatch_interaction(
            {"type": 2, "token": "t", "data": {"name": "ping"}},
            _ApiFalsa(),
            registry=reg,
        )

        assert ok is False

    async def test_tipo_sem_ramo_false(self) -> None:
        """`PING` chega pelo endpoint HTTP, não pelo Gateway."""
        reg, _ = _registro_com()

        ok = await dispatch_interaction(
            {"id": "1", "type": 1, "token": "t"},
            _ApiFalsa(),
            registry=reg,
        )

        assert ok is False

    async def test_on_not_found_de_comando_nao_vai_para_responder(self) -> None:
        """São dois `Options` diferentes, e trocá-los faria um comando
        inexistente responder "isso não foi configurado" na hora errada
        (`0026` §4)."""
        reg = Registry()
        comandos: list[Any] = []
        responders: list[Any] = []

        #: Um argumento só nos dois — `on_not_found` não tem erro para
        #: passar (`0029`). Escrever dois levantaria `TypeError` no
        #: ramo errado, que é exatamente o bug que este teste pega.
        async def achou_comando(ctx: Any) -> None:
            comandos.append(ctx)

        async def achou_responder(ctx: Any) -> None:
            responders.append(ctx)

        await dispatch_interaction(
            {
                "id": "1",
                "type": 3,
                "token": "t",
                "data": {"custom_id": "/nada", "component_type": 2},
            },
            _ApiFalsa(),
            registry=reg,
            command_options=CommandOptions(on_not_found=achou_comando),
            responder_options=ResponderOptions(on_not_found=achou_responder),
        )

        assert comandos == []
        assert len(responders) == 1

    async def test_on_not_found_aceita_um_argumento_nos_dois_ramos(self) -> None:
        """O `0029` fechou a assinatura: `(ctx)` só, nos dois ramos.
        Este caso existe porque a divergência sobreviveu justamente
        porque só o lado de responder tinha teste."""
        reg = Registry()
        chamou: list[str] = []

        async def comando_desconhecido(ctx: Any) -> None:
            chamou.append("comando")

        async def responder_desconhecido(ctx: Any) -> None:
            chamou.append("responder")

        opcoes_comando = CommandOptions(on_not_found=comando_desconhecido)
        opcoes_responder = ResponderOptions(on_not_found=responder_desconhecido)

        await dispatch_interaction(
            {"id": "1", "type": 2, "token": "t", "data": {"name": "fantasma"}},
            _ApiFalsa(),
            registry=reg,
            command_options=opcoes_comando,
            responder_options=opcoes_responder,
        )
        await dispatch_interaction(
            {
                "id": "1",
                "type": 3,
                "token": "t",
                "data": {"custom_id": "/nada", "component_type": 2},
            },
            _ApiFalsa(),
            registry=reg,
            command_options=opcoes_comando,
            responder_options=opcoes_responder,
        )

        assert chamou == ["comando", "responder"]


# ==========================================================================
# Ordem: roteamento antes de @event (0025 §4)
# ==========================================================================


class TestOrdemDoDispatch:
    async def test_roteamento_antes_do_event(self) -> None:
        """A etapa 4 vem antes da etapa 5. Reverter faria o `@event`
        ver o clique antes de o comando tê-lo atendido — e o handler
        que lê estado defasado é o pior tipo de bug: aparece só sob
        carga, e desaparece quando alguém para o bot para olhar."""
        reg = Registry()
        cliente = Client(Config(intents=Intents.default()), registry=reg)
        ordem: list[str] = []

        inst = create_command(name="ping", description="Ping", registry=reg.commands)

        @inst
        async def ping(ctx: CommandInteraction) -> None:
            ordem.append("comando")

        @event("interaction_create", registry=reg.events)
        async def visto(inter: Interaction) -> None:
            ordem.append("evento")

        await cliente.dispatch(
            "INTERACTION_CREATE",
            {"id": "1", "type": 2, "token": "t", "data": {"name": "ping"}},
        )

        assert ordem == ["comando", "evento"]

    async def test_state_do_comando_e_visivel_no_event(self) -> None:
        """O dicionário é **um só por dispatch**: é o que faz a etapa 4
        e a middleware de evento da etapa 5 carregarem o mesmo estado
        sem serem o mesmo objeto. O handler de `@event` recebe só o
        payload (`0031`) — quem no lado do evento lê o estado é a
        middleware, que enxerga o quadro interno."""
        lido: list[Any] = []

        async def ve(frame: Any, block: Any) -> None:
            lido.append(frame.state.get("visto"))

        reg = Registry()
        cliente = Client(
            Config(intents=Intents.default(), events=EventOptions(middleware=ve)),
            registry=reg,
        )

        inst = create_command(name="ping", description="Ping", registry=reg.commands)

        @inst
        async def ping(ctx: CommandInteraction) -> None:
            ctx.state["visto"] = "pelo-comando"

        @event("interaction_create", registry=reg.events)
        async def visto(inter: Interaction) -> None: ...

        await cliente.dispatch(
            "INTERACTION_CREATE",
            {"id": "1", "type": 2, "token": "t", "data": {"name": "ping"}},
        )

        assert lido == ["pelo-comando"]

    async def test_nao_interacao_passa_direto(self) -> None:
        """Tudo que não é interação custa um `if` e nada mais — e o
        evento segue normalmente."""
        reg = Registry()
        cliente = Client(Config(intents=Intents.default()), registry=reg)
        recebido: list[Any] = []

        @event("message_create", registry=reg.events)
        async def criado(msg: Any) -> None:
            recebido.append(msg)

        await cliente.dispatch(
            "MESSAGE_CREATE",
            {
                "id": "1",
                "channel_id": "2",
                "author": {"id": "9", "username": "x"},
                "content": "oi",
            },
        )

        assert len(recebido) == 1


# ---------------------------------------------------------------------------
# O `api` que desce do `Client`
# ---------------------------------------------------------------------------


class TestApiRealNoDespacho:
    """O `Client` entrega `client.api` — o `DiscordAPI` **raiz** — ao
    despacho; os contextos guardam o namespace (`api.interactions`), e
    o `interacoes_de` na entrada de cada ramo é quem garante isso
    (`0007`: cada camada com o vocabulário da camada).

    Bug que estes testes prendem: `DiscordAPI` não tem `respond`, e a
    `/ping` ao vivo morria com `AttributeError` dentro da resposta.
    Passou pelos testes inteiros porque o duplo de `api` era plano."""

    async def test_comando_responde_pelo_callback(self) -> None:
        reg = Registry()
        api, captured = make_api(no_content())

        inst = create_command(name="ping", description="Ping", registry=reg.commands)

        @inst
        async def ping(ctx: CommandInteraction) -> None:
            await ctx.respond("pong")

        ok = await dispatch_interaction(
            {"id": "111", "type": 2, "token": "tk", "data": {"name": "ping"}},
            api,
            registry=reg,
        )

        assert ok is True
        assert captured[0].url.path == "/api/v10/interactions/111/tk/callback"
        corpo = json.loads(captured[0].content)
        assert corpo["type"] == 4
        assert corpo["data"]["content"] == "pong"

    async def test_responder_atualiza_pelo_callback(self) -> None:
        """O ramo de componentes é outro ponto de entrada — o mesmo
        namespace normalizado, o mesmo `update` plano no contexto."""
        reg = Registry()
        api, captured = make_api(no_content())

        async def clicou(ctx: Any) -> None:
            await ctx.update("ok")

        reg.responders.register("/ping", clicou, types=(ResponderType.BUTTON,))

        ok = await dispatch_interaction(
            {
                "id": "111",
                "type": 3,
                "token": "tk",
                "data": {"custom_id": "/ping", "component_type": 2},
            },
            api,
            registry=reg,
        )

        assert ok is True
        assert captured[0].url.path == "/api/v10/interactions/111/tk/callback"
        corpo = json.loads(captured[0].content)
        assert corpo["type"] == 7
        assert corpo["data"]["content"] == "ok"

    async def test_autocomplete_com_handler_usa_o_namespace(self) -> None:
        """A `AutocompleteInteraction` recebe o `api` **também** como
        parâmetro próprio — o mesmo namespace, o mesmo tipo 8."""
        reg = Registry()
        api, captured = make_api(no_content())

        inst = create_command(name="ping", description="Ping", registry=reg.commands)

        @inst
        async def ping(ctx: CommandInteraction) -> None: ...

        @inst.autocomplete()
        async def sugere(ctx: AutocompleteInteraction) -> list[dict[str, Any]]:
            return [{"name": "pinguim", "value": "ping"}]

        ok = await dispatch_interaction(
            {
                "id": "111",
                "type": 4,
                "token": "tk",
                "data": {
                    "name": "ping",
                    "options": [{"type": 3, "name": "q", "value": "pi", "focused": True}],
                },
            },
            api,
            registry=reg,
        )

        assert ok is True
        assert captured[0].url.path == "/api/v10/interactions/111/tk/callback"
        corpo = json.loads(captured[0].content)
        assert corpo["type"] == 8
        assert corpo["data"]["choices"] == [{"name": "pinguim", "value": "ping"}]

    async def test_autocomplete_sem_handler_responde_vazio(self) -> None:
        """O fallback vazio (0021) chama `api.autocomplete` direto no
        parâmetro cru — o `interacoes_de` da entrada cobre ele também."""
        reg = Registry()
        api, captured = make_api(no_content())

        inst = create_command(name="ping", description="Ping", registry=reg.commands)

        @inst
        async def ping(ctx: CommandInteraction) -> None: ...

        ok = await dispatch_interaction(
            {
                "id": "111",
                "type": 4,
                "token": "tk",
                "data": {
                    "name": "ping",
                    "options": [{"type": 3, "name": "q", "value": "pi", "focused": True}],
                },
            },
            api,
            registry=reg,
        )

        assert ok is False
        assert captured[0].url.path == "/api/v10/interactions/111/tk/callback"
        corpo = json.loads(captured[0].content)
        assert corpo["type"] == 8
        assert corpo["data"]["choices"] == []
