"""`patterns.py` — match, backtracking e prioridade (0013).

O fio: o caso que **exige** backtracking (`/a/{?x}/b` casando `/a/b`)
é o que separa um roteador de uma lista de `if`. Sem voltar atrás, a
rota mais natural simplesmente não funcionaria.
"""

from __future__ import annotations

from kryncord.responders.patterns import Padrao, conflitam, ordena


class TestMatch:
    def test_literal_casa_exato(self) -> None:
        assert Padrao("/system/confirm").casa("/system/confirm") == {}
        assert Padrao("/system/confirm").casa("/system/outro") is None

    def test_param_extrai_valor(self) -> None:
        achado = Padrao("/manage/user/{user_id}/{action}").casa("/manage/user/123/ban")

        assert achado == {"user_id": "123", "action": "ban"}

    def test_param_casa_valor_com_dois_pontos(self) -> None:
        """A 0013: `:` não é sintaxe em lugar nenhum — o param casa
        qualquer coisa sem `/`. Um timestamp ISO não quebra o casamento."""
        achado = Padrao("/remember/{date}").casa("/remember/2024-01-01T10:00:00")

        assert achado == {"date": "2024-01-01T10:00:00"}

    def test_segmento_a_mais_nao_casa(self) -> None:
        assert Padrao("/manage/user/{user_id}/{action}").casa("/manage/user/123") is None

    def test_id_sem_barra_casa(self) -> None:
        """O id construído sempre vem com barra; o que vem do Discord
        pode não vir, e recusar seria recusar botão legítimo."""
        assert Padrao("/system/confirm").casa("system/confirm") == {}

    def test_trailing_slash_casa(self) -> None:
        assert Padrao("/system/confirm").casa("/system/confirm/") == {}

    def test_id_vazio_nao_casa(self) -> None:
        assert Padrao("/system/confirm").casa("") is None

    def test_literal_nao_faz_case_folding(self) -> None:
        """`custom_id` é gerado por nós, não digitado por humano —
        normalizar seria trabalho sem cliente (0013)."""
        assert Padrao("/System/Confirm").casa("/system/confirm") is None


class TestOpcional:
    def test_opcional_presente(self) -> None:
        assert Padrao("/page/{?number}").casa("/page/2") == {"number": "2"}

    def test_opcional_ausente(self) -> None:
        """Ausente é **não estar no dict**, não estar como `""` —
        converter `""` para int daria erro num param que nem veio."""
        assert Padrao("/page/{?number}").casa("/page") == {}

    def test_backtracking_obrigatorio(self) -> None:
        """O caso que exige voltar atrás: `{?x}` casa zero para que o
        literal `b` feche a rota. Sem backtracking, não casa nunca."""
        achado = Padrao("/a/{?x}/b").casa("/a/b")

        assert achado == {}

    def test_backtracking_com_valor(self) -> None:
        assert Padrao("/a/{?x}/b").casa("/a/1/b") == {"x": "1"}

    def test_dois_opcionais(self) -> None:
        padrao = Padrao("/a/{?x}/{?y}")

        assert padrao.casa("/a") == {}
        assert padrao.casa("/a/1") == {"x": "1"}
        assert padrao.casa("/a/1/2") == {"x": "1", "y": "2"}


class TestWildcard:
    def test_casa_zero_segmentos(self) -> None:
        assert Padrao("/giveaway/**").casa("/giveaway") == {"_": ""}

    def test_casa_varios_segmentos(self) -> None:
        achado = Padrao("/giveaway/**").casa("/giveaway/gifts/nitro")

        assert achado == {"_": "gifts/nitro"}

    def test_sem_prefixo_nao_casa(self) -> None:
        assert Padrao("/giveaway/**").casa("/outro/gifts") is None

    def test_nomeado_exige_pelo_menos_um(self) -> None:
        """`**` sem nome casa zero; nomeado exige — a 0013 fechou a
        diferença: quem nomeou, quer o resto."""
        assert Padrao("/giveaway/**{args}").casa("/giveaway") is None
        assert Padrao("/giveaway/**{args}").casa("/giveaway/users") == {"args": "users"}


class TestPrioridade:
    """A ordem da 0013: literal > `{p}` > `{?p}` > `**`, da esquerda."""

    def test_literal_vence_param(self) -> None:
        a, b = Padrao("/a/{x}"), Padrao("/{y}/b")
        assert ordena([b, a])[0] is a

    def test_mais_fixos_primeiro(self) -> None:
        rotas = ["/manage/**", "/manage/user/{id}/{action}", "/manage/user/{id}/ban"]
        ordenada = [p.rota for p in ordena([Padrao(r) for r in rotas])]

        assert ordenada == [
            "/manage/user/{id}/ban",
            "/manage/user/{id}/{action}",
            "/manage/**",
        ]

    def test_prefixo_curto_vence_o_com_wildcard(self) -> None:
        """`/a/{b}` termina exato; `/a/{b}/**` casaria os mesmos ids com
        peso empatado — o curto é o mais específico."""
        curto, longo = Padrao("/a/{b}"), Padrao("/a/{b}/**")

        assert ordena([longo, curto])[0] is curto

    def test_opcional_pesa_menos_que_obrigatorio(self) -> None:
        obrigatorio, opcional = Padrao("/a/{b}"), Padrao("/a/{?b}")

        assert ordena([opcional, obrigatorio])[0] is obrigatorio


class TestConflitam:
    def test_mesmos_pesos_literais_diferentes_nao_conflitam(self) -> None:
        """/a/{x} e /b/{y} têm o mesmo peso mas nunca casam o mesmo id."""
        assert conflitam(Padrao("/a/{x}"), Padrao("/b/{y}")) is False

    def test_literais_contra_params_conflitam(self) -> None:
        """/a/{x} e /a/{y} têm o mesmo peso e casam /a/1 — os dois, e
        ninguém decide qual."""
        assert conflitam(Padrao("/a/{x}"), Padrao("/a/{y}")) is True

    def test_pesos_diferentes_nao_conflitam(self) -> None:
        """/a/{x} (3,2) e /{y}/b (2,3) casam /a/b — mas a prioridade
        resolve: literal na frente pesa mais. Empate exato é o único
        conflito, porque é o único que a ordem não decide."""
        assert conflitam(Padrao("/a/{x}"), Padrao("/{y}/b")) is False

    def test_rotas_iguais_conflitam(self) -> None:
        assert conflitam(Padrao("/x/y"), Padrao("/x/y")) is True

    def test_obrigatorio_nao_conflita_com_opcional(self) -> None:
        """Pesos diferentes — a prioridade decide: `{x}` (2) antes de
        `{?x}` (1) para o mesmo id."""
        assert conflitam(Padrao("/a/{x}"), Padrao("/a/{?x}")) is False
