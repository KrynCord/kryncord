"""Testes do `bootstrap` — a ordem dos imports é a garantia do `0019`.

O `bootstrap` importa, chama `before_load`, conta o que entrou e devolve
`Client`. Ele **não** sobe o bot (`K4`) e **não** publica comando — e
esses dois "não" são o que mais se tenta adicionar depois, então estão
testados.

Os pacotes-fixture são `pacote_teste*` (ver `pacote_teste/__init__.py`):
cada módulo anota o próprio nome em `ORDEM`, na ordem em que executou.
Sem isso não há como provar "pai antes de filho" sem olhar `sys.modules`,
que qualquer teste anterior já populou.

Nenhum teste aqui toca rede nem dorme: `bootstrap` nunca chama `start()`.
"""

import logging
import sys

import pytest

from kryncord import Client, Config, Intents, bootstrap
from kryncord.enums import ResponderType
from kryncord.registry import Registry

PAQUETES = ("pacote_teste", "pacote_quebrado", "pacote_circular")


def limpa() -> None:
    """Zera a ordem observável e tira os pacotes-fixture do cache."""
    from registro_ordem import ORDEM

    ORDEM.clear()
    for nome in [n for n in sys.modules if n.split(".")[0] in PAQUETES]:
        del sys.modules[nome]


@pytest.fixture(autouse=True)
def _limpa_fixtures():
    limpa()
    yield
    limpa()


@pytest.fixture
def ordem() -> list[str]:
    """A lista de ordem do fixture, já zerada pelo `limpa`.

    `registro_ordem` não é pacote-fixture: importá-lo aqui não esconde
    `pacote_teste` de dentro do resultado do bootstrap.
    """
    from registro_ordem import ORDEM

    return ORDEM


@pytest.fixture
def cliente() -> Client:
    """Um `Client` com registry próprio — nunca o global (`K12`)."""
    return Client(Config(intents=Intents.default()), registry=Registry())


@pytest.fixture
def captura():
    """Grava os registros do logger `kryncord.discovery` direto nele.

    `caplog` pega no logger raiz, mas `setup_logging()` pode ter posto
    `propagate = False` no `kryncord` — e aí o teste falharia por
    motivo de configuração, não por motivo de código. Colar o handler
    no logger exato é imune a isso.
    """
    capturados: list[str] = []
    logger = logging.getLogger("kryncord.discovery")

    class _Captura(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            capturados.append(record.getMessage())

    handler = _Captura()
    nivel_anterior = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield capturados
    finally:
        logger.removeHandler(handler)
        logger.setLevel(nivel_anterior)


class TestOrdem:
    async def test_pai_importa_antes_do_filho(self, cliente: Client, ordem: list[str]) -> None:
        """A 04 §2 vence a 01 §3 r3: a ordem é garantida, não esperada.

        `sorted` por profundidade com desempate alfabético. Sem isso,
        dois irmãos trocariam de lugar entre execuções e o `load_logs`
        pareceria mudar sem motivo.
        """
        await bootstrap(modules=["pacote_teste.**"], load_logs=False, client=cliente)

        assert ordem[0] == "pacote_teste"
        assert ordem.index("pacote_teste.sub") < ordem.index("pacote_teste.sub.profundo")
        assert ordem == sorted(ordem, key=lambda n: (n.count("."), n))

    async def test_tudo_que_o_glob_casou_foi_importado(
        self, cliente: Client, ordem: list[str]
    ) -> None:
        await bootstrap(modules=["pacote_teste.**"], load_logs=False, client=cliente)

        assert set(ordem) == {
            "pacote_teste",
            "pacote_teste.alpha_mod",
            "pacote_teste.beta_mod",
            "pacote_teste.sub",
            "pacote_teste.sub.profundo",
            "pacote_teste.util",
        }

    async def test_padrao_sem_casamento_nao_derruba(self, cliente: Client) -> None:
        """O caso do `B1`: o glob existe para poder ser agressivo sem
        arrastar módulo errado. Falhar aqui puniria quem usou certo."""
        alvo = await bootstrap(
            modules=["pacote_teste.nao_tem_filho_*"], load_logs=False, client=cliente
        )

        assert alvo is cliente

    async def test_modules_vazio_devolve_quem_passou(self, cliente: Client) -> None:
        """Descoberta automática nunca é obrigatória — `modules=()` é o
        caso do `mybot/__init__.py` que já registra tudo na mão."""
        assert await bootstrap(load_logs=False, client=cliente) is cliente


class TestBeforeLoad:
    async def test_assincrono_roda_depois_dos_imports(
        self, cliente: Client, ordem: list[str]
    ) -> None:
        """É a correção do `0027` §1: um `bootstrap` síncrono não tem
        onde esperar uma coroutine, e a ideia 01 §2 sempre escreveu
        `await bootstrap(...)`."""
        visto: list[int] = []

        async def antes(client: Client) -> None:
            visto.append(len(ordem))
            assert client is cliente

        await bootstrap(
            modules=["pacote_teste.**"],
            load_logs=False,
            before_load=antes,
            client=cliente,
        )

        assert visto == [6]

    async def test_sincrono_tambem_e_adaptado(self, cliente: Client) -> None:
        """`B3`: `inspect.isawaitable` decide, e não o tipo declarado —
        `Callable[[Client], None]` tem que funcionar sem `async`."""
        chamado: list[str] = []

        def antes(client: Client) -> None:
            chamado.append("sim")

        await bootstrap(load_logs=False, before_load=antes, client=cliente)

        assert chamado == ["sim"]

    async def test_nao_roda_quando_e_none(self, cliente: Client, ordem: list[str]) -> None:
        await bootstrap(modules=["pacote_teste.util"], load_logs=False, client=cliente)

        assert ordem == ["pacote_teste", "pacote_teste.util"]


class TestFalhaPropaga:
    async def test_import_quebrado_cita_modulo_e_padrao(self) -> None:
        """`0027` §5: sem o padrão, um `**` de 40 módulos não diz qual
        dos 40 falhou nem qual padrão o trouxe."""
        with pytest.raises(ImportError, match=r"pacote_quebrado\.estoura") as erro:
            await bootstrap(modules=["pacote_quebrado.**"], load_logs=False)

        assert "pacote_quebrado.**" in str(erro.value)

    async def test_a_causa_original_fica_visivel(self) -> None:
        """`from exc` dentro do `except` — o `RuntimeError` é a causa,
        não um detalhe perdido."""
        with pytest.raises(ImportError) as erro:
            await bootstrap(modules=["pacote_quebrado.estoura"], load_logs=False)

        assert isinstance(erro.value.__cause__, RuntimeError)
        assert "estouro proposital" in str(erro.value.__cause__)

    async def test_circular_aponta_sem_corrigir(self) -> None:
        """`0027` §6: auto-correção é magia. Mostra a saída e sugere a
        ordem explícita — quem escreveu o ciclo é quem tem que decidir.
        """
        with pytest.raises(ImportError, match="importação circular") as erro:
            await bootstrap(modules=["pacote_circular.a"], load_logs=False)

        assert "bootstrap(modules=" in str(erro.value)
        assert isinstance(erro.value.__cause__, ImportError)

    async def test_base_inexistente_e_module_not_found(self) -> None:
        """Erro de digitação: o loader sabe o nome, e virar um padrão
        "que não casou nada" esconderia o typo (`0027` §8)."""
        with pytest.raises(ModuleNotFoundError, match="nao_existe_nenhum"):
            await bootstrap(modules=["nao_existe_nenhum.**"], load_logs=False)


class TestNaoSobeONada:
    async def test_devolve_sem_ligar_o_bot(self, cliente: Client) -> None:
        """`K4`: o ciclo de vida é do chamador. `start()`, `sync()` e
        a publicação de comando ficam todos do lado de fora."""
        await bootstrap(modules=["pacote_teste.**"], load_logs=False, client=cliente)

        assert not cliente.is_started
        assert not cliente.is_ready
        assert not cliente.is_closed
        assert cliente.config.token == ""

    async def test_quando_nao_passa_client_um_e_criado(self) -> None:
        """O caso da ideia 01 §2: `bootstrap(...)` → `client.run(tok)`."""
        alvo = await bootstrap(load_logs=False)

        assert isinstance(alvo, Client)
        assert alvo.config.token == ""


class TestLoadLogs:
    async def test_false_nao_emite_nada(self, cliente: Client, captura: list[str]) -> None:
        """`load_logs=False` vira `DISABLED` nesse logger — na prática,
        não emite. O nível de fora não é tocado: quem configurou um
        handler próprio continua mandando o resto do `kryncord`."""
        await bootstrap(modules=["pacote_teste.**"], load_logs=False, client=cliente)

        assert captura == []

    async def test_agrupa_por_modulo_do_handler(self, cliente: Client, captura: list[str]) -> None:
        """Agrupar **depois**, e não contar delta por import: um módulo
        que só re-exporta registra de outro, e o delta atribuiria o
        comando a quem importou, não a quem escreveu (`0027` §7).

        O handler é registrado daqui, mas `__module__` diz de onde ele
        veio — e é isso que o log reporta.
        """
        from pacote_teste.handlers import orfao

        from kryncord import command

        command(
            name="orfao",
            description="Registrado de fora do módulo que o define",
            registry=cliente.commands,
        )(orfao)

        await bootstrap(modules=["pacote_teste.util"], client=cliente)

        assert "[pacote_teste.handlers] 1 comando, 0 responders" in captura
        assert "[pacote_teste.util] 0 comandos, 0 responders" in captura

    async def test_linha_com_zero_continua_aparecendo(
        self, cliente: Client, captura: list[str]
    ) -> None:
        """ "Não apareceu" é a informação — e ela só existe quando a
        linha existe com o zero nela (`0019` §5)."""
        await bootstrap(modules=["pacote_teste.util"], client=cliente)

        assert any(
            linha.startswith("[pacote_teste.util] 0 comandos, 0 responders") for linha in captura
        )
        assert captura[-1] == "carregados 1 módulo, 0 comandos, 0 responders"

    async def test_total_final_conta_o_que_registrou(
        self, cliente: Client, captura: list[str]
    ) -> None:
        from kryncord import CommandInteraction, command

        @command(name="ping", description="Ping", registry=cliente.commands)
        async def ping(inter: CommandInteraction) -> None:  # pragma: no cover - só registra
            raise AssertionError("não devia rodar")

        cliente.responders.register(
            "ping",
            ping,
            types=(ResponderType.BUTTON,),
        )

        await bootstrap(modules=["pacote_teste.util"], client=cliente)

        assert any(linha == "[test_bootstrap] 1 comando, 1 responder" for linha in captura)
        assert captura[-1] == "carregados 1 módulo, 1 comando, 1 responder"

    async def test_singular_e_plural_no_log(self, cliente: Client, captura: list[str]) -> None:
        """`plural` do Python faria "1 comandos". Um log que erra o
        próprio texto ensina a desconfiar do resto."""
        from kryncord import CommandInteraction, command

        @command(name="ping", description="Ping", registry=cliente.commands)
        async def ping(inter: CommandInteraction) -> None:  # pragma: no cover - só registra
            raise AssertionError("não devia rodar")

        @command(name="pong", description="Pong", registry=cliente.commands)
        async def pong(inter: CommandInteraction) -> None:  # pragma: no cover - só registra
            raise AssertionError("não devia rodar")

        await bootstrap(load_logs=False, client=cliente)
        captura.clear()

        await bootstrap(load_logs=True, client=cliente)

        assert captura[-1] == "carregados 0 módulos, 2 comandos, 0 responders"
