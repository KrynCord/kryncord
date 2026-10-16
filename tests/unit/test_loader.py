"""Testes do loader — a sintaxe do glob, coberta sem importar nada.

`resolve` é puro (`0027` §2): nenhum efeito colateral, nenhum
`sys.modules` mutado pelo que a varredura descobre. É por isso que
estes testes existem no formato em que existem — a ideia 01 §8 pede
um `test_loader.py` sem `sys.path` e sem rede.

O que a varredura pode disparar de import é só o do **ancestral** da
base, e é inevitável em Python. O teste de "não executa o que não casa"
confere o que é nosso: a base nem ninguém embaixo dela entra em
`sys.modules`.
"""

import sys

import pytest

from kryncord.discovery import resolve, resolve_todos

PAQUETES = ("pacote_teste", "pacote_quebrado", "pacote_circular")


@pytest.fixture(autouse=True)
def _limpa_fixtures():
    """Tira os pacotes-fixture de `sys.modules` antes e depois de cada caso.

    Sem isto, o cache do import faria o segundo teste ver tudo já
    carregado e concluiria que `resolve` não executa nada — falso por
    motivo errado. E sem o `after`, o próximo arquivo de teste veria
    `pacote_teste` já importado e a ordem sairia vazia.
    """
    limpa()
    yield
    limpa()


def limpa() -> None:
    """Remove os módulos-fixture do cache do import e zera a ordem."""
    from registro_ordem import ORDEM

    ORDEM.clear()
    for nome in [n for n in sys.modules if n.split(".")[0] in PAQUETES]:
        del sys.modules[nome]


class TestSintaxe:
    def test_padrao_exato_devolve_o_proprio(self) -> None:
        assert resolve("pacote_teste.util") == ("pacote_teste.util",)

    def test_estrela_nao_inclui_o_pacote(self) -> None:
        """`*` é "os filhos". Incluir o pai duplicaria tudo que o `**`
        já traz, e o `**` existiria sem pagar nada por isso."""
        filhos = resolve("pacote_teste.*")
        assert "pacote_teste" not in filhos
        assert "pacote_teste.util" in filhos
        assert "pacote_teste.sub" in filhos

    def test_estrela_dupla_inclui_o_pacote_e_tudo_abaixo(self) -> None:
        tudo = resolve("pacote_teste.**")
        assert "pacote_teste" in tudo
        assert "pacote_teste.util" in tudo
        assert "pacote_teste.sub" in tudo
        assert "pacote_teste.sub.profundo" in tudo

    def test_estrela_dupla_desce_uma_vez_mais_que_a_simples(self) -> None:
        simples = set(resolve("pacote_teste.*"))
        dupla = set(resolve("pacote_teste.**"))
        assert dupla - simples == {"pacote_teste", "pacote_teste.sub.profundo"}

    def test_sufixo_py_marca_padrao_de_arquivo(self) -> None:
        """`.py` sai **antes** do parse, e o que sobra é padrão de
        módulo (`0027` §3). Nada de caminho — o `K5` proíbe a barra."""
        assert resolve("pacote_teste.util.py") == ("pacote_teste.util",)

    def test_curinga_com_sufixo_casa_só_o_que_tem_o_sufixo(self) -> None:
        """`*_mod` é o `B1`: o glob existe para poder ser agressivo
        sem arrastar `util.py` nem `sub/`."""
        achados = resolve("pacote_teste.*_mod.py")
        assert achados == ("pacote_teste.alpha_mod", "pacote_teste.beta_mod")

    def test_caminho_de_disco_nao_e_padrao(self) -> None:
        """`bot testes/main.py` tem espaço e barra — nunca vira
        pacote. O ponto é o separador, sempre."""
        with pytest.raises(ModuleNotFoundError, match="base"):
            resolve("tests/unit/pacote_teste")

    def test_subpacote_exato(self) -> None:
        assert resolve("pacote_teste.sub") == ("pacote_teste.sub",)

    def test_curinga_no_meio(self) -> None:
        """Um segmento só, e o literal depois tem que existir."""
        assert resolve("pacote_teste.*.profundo") == ("pacote_teste.sub.profundo",)


class TestBaseInexistente:
    def test_pacote_inexistente_e_module_not_found(self) -> None:
        """Erro de digitação, e o loader sabe o nome (`0027` §8).
        Devolver `()` esconderia o typo atrás de um bot que não
        registrou nada."""
        with pytest.raises(ModuleNotFoundError, match="nao_existe_nenhum"):
            resolve("nao_existe_nenhum.comandos.**")

    def test_subpacote_inexistente_tambem(self) -> None:
        with pytest.raises(ModuleNotFoundError, match="pacote_teste"):
            resolve("pacote_teste.nada.**")

    def test_mensagem_cita_o_padrao_original(self) -> None:
        """Sem o padrão, um typo num `**` de 40 módulos não diz onde
        olhar."""
        with pytest.raises(ModuleNotFoundError, match=r"pacote_teste\.nada\.\*\*"):
            resolve("pacote_teste.nada.**")

    def test_curinga_na_frente_e_erro(self) -> None:
        """`*.comandos` não tem nome de pacote — e `find_spec("")`
        daria `ValueError`, que é uma mensagem que não aponta nada."""
        with pytest.raises(ModuleNotFoundError, match="base"):
            resolve("*.comandos")


class TestSemCasamento:
    def test_base_existe_sem_filho_devolve_vazio(self) -> None:
        """É o caso legítimo do `*_mod.py`: falhar porque ainda não há
        nenhum arquivo `_mod` obrigaria a criar um vazio (`0027` §8)."""
        assert resolve("pacote_teste.nao_tem_filho_*") == ()

    def test_base_e_modulo_nao_pacote_devolve_vazio(self) -> None:
        """`mybot.main.*` onde `main` é módulo: não tem filho, e isso
        é informação, não falha."""
        assert resolve("pacote_teste.util.*") == ()


class TestResolveTodos:
    def test_ordena_por_profundidade_com_desempate_alphabetico(self) -> None:
        """Pai antes de filho é a garantia do `0019`; o desempate é o
        que faz o `load_logs` ser estável entre execuções."""
        nomes, _origem = resolve_todos(["pacote_teste.**"])

        assert nomes[0] == "pacote_teste"
        assert nomes.index("pacote_teste.sub") < nomes.index("pacote_teste.sub.profundo")
        assert nomes == sorted(nomes, key=lambda n: (n.count("."), n))

    def test_sobreposicao_nao_duplica(self) -> None:
        """`pacote_teste` e `pacote_teste.**` no mesmo `modules` não é
        erro — `sys.modules` já cacheia (`0027` §3)."""
        nomes, origem = resolve_todos(["pacote_teste", "pacote_teste.**"])

        assert len(nomes) == len(set(nomes))
        assert "pacote_teste" in nomes
        # A origem é a do **primeiro** padrão que trouxe o nome: é o que
        # o `ImportError` vai citar quando der errado.
        assert origem["pacote_teste"] == "pacote_teste"

    def test_origem_cobre_todos_os_nomes(self) -> None:
        """Sem origem, uma falha num `**` de 40 módulos não diz qual
        padrão o trouxe."""
        nomes, origem = resolve_todos(["pacote_teste.*", "pacote_quebrado.*"])

        assert set(nomes) <= set(origem)

    def test_padrao_sem_casamento_so_loga_debug(self) -> None:
        """Não é erro — e o loader registra, para quem estiver olhando
        o log, saber que o padrão rodou e não achou."""
        nomes, origem = resolve_todos(["pacote_teste.nao_tem_filho_*"])

        assert nomes == []
        assert origem == {}


class TestNaoExecutaONaoCasado:
    def test_a_varredura_nao_importa_os_filhos(self) -> None:
        """O ponto do `0027` §2: nem o alvo nem ninguém embaixo dele
        pode ser executado pela resolução.

        O caso que separa o certo do "quase certo" é o **neto**:
        `find_spec("a.b.c")` importa `a.b` para achar `c`, e isso
        executaria um pacote antes da fase de import — quebrando a
        garantia de ordem do `0019`. Por isso a varredura percorre
        diretório, um nível por vez.
        """
        resolve("pacote_teste.**")

        assert "pacote_teste" not in sys.modules
        assert "pacote_teste.sub" not in sys.modules
        assert "pacote_teste.sub.profundo" not in sys.modules
        assert "pacote_teste.util" not in sys.modules
        assert "pacote_teste.alpha_mod" not in sys.modules
