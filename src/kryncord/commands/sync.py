"""Sincronização de comandos — o `sync()`.

A forma escolhida é **bulk `PUT` por escopo** (`0018`). `PATCH` por
comando custaria uma requisição cada, e o rate limit real aqui é o
**global: 2 por hora** — com 50 comandos, um sync completo levaria 25
minutos.

Antes de enviar, o `sync()` **busca o remoto e compara**. Um sync sem
mudança faz uma chamada `GET` por escopo e nenhuma escrita. Sem isto,
todo boot reenviaria a lista inteira e o `verbose` mentiria dizendo
"criado" para comando que já existia.

O `sync(apply=False)` é o dry-run: devolve o relatório sem tocar no
Discord. É a única forma de auditar o que mudaria sem rede.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from kryncord.commands.registry import CommandRegistry
from kryncord.commands.validation import validate_definition
from kryncord.enums import ApplicationCommandType
from kryncord.logging import get_logger
from kryncord.models.command import ApplicationCommand

_log = get_logger(__name__)


class SyncAction(StrEnum):
    """O que aconteceu com um comando.

    Vocabulário de diff que todo mundo já lê — `aparar`/`remover`
    seria inventar sinônimo.
    """

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    UNCHANGED = "unchanged"


#: `(escopo, nome_com_tipo)`. Par explícito: o escopo é metade da
#: informação, e guardá-lo dentro de string obrigaria a recuperá-lo
#: com corte depois.
Entrada = tuple[int | None, str]


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Resultado de um `sync()`.

    Existe porque sem ele o teste teria que espionar o transporte — e
    o relatório é barato.
    """

    created: tuple[Entrada, ...] = ()
    updated: tuple[Entrada, ...] = ()
    deleted: tuple[Entrada, ...] = ()
    unchanged: tuple[Entrada, ...] = ()
    scopes: tuple[int | None, ...] = ()
    aplicado: bool = True
    """Se as mudanças foram mandadas. `False` em `apply=False`."""

    @property
    def mudancas(self) -> int:
        return len(self.created) + len(self.updated) + len(self.deleted)

    @property
    def vazio(self) -> bool:
        """Nada mudou — o caso mais comum em boot."""
        return self.mudancas == 0

    def linhas(self) -> list[str]:
        """Linhas para o `verbose`. Uma por comando que mudou, com o
        escopo — sem o escopo, "criado" não diz para onde foi."""
        rotulo = {
            SyncAction.CREATED: "criado",
            SyncAction.UPDATED: "atualizado",
            SyncAction.DELETED: "removido",
        }
        saida: list[str] = []
        for acao, nomes in (
            (SyncAction.CREATED, self.created),
            (SyncAction.UPDATED, self.updated),
            (SyncAction.DELETED, self.deleted),
        ):
            for escopo, nome in nomes:
                alvo = "global" if escopo is None else f"guild {escopo}"
                saida.append(f"  [{rotulo[acao]:<11}] {nome} -> {alvo}")
        return saida


class CommandSync:
    """Leva o registry ao Discord."""

    __slots__ = ("_api", "_app_id", "_registry")

    def __init__(self, registry: CommandRegistry, applications: Any) -> None:
        self._registry = registry
        #: `ApplicationsAPI` — só usa `me()`, `list_commands` e
        #: `bulk_overwrite_commands`, todos com `guild_id=`.
        self._api = applications
        self._app_id: int | None = None
        """Cacheado: é o mesmo para todos os escopos, e buscar duas
        vezes é uma requisição a mais por boot."""

    async def sync(self, *, apply: bool = True, verbose: bool = False) -> SyncReport:
        """Sincroniza todos os escopos registrados.

        `apply=False` é dry-run: calcula e devolve, sem enviar. Não
        espera rate limit porque não manda nada.
        """
        self._valida_tudo()

        escopos = self._registry.scopes()
        if not escopos:
            # Registro vazio quase sempre é bug de registro, não
            # intenção — e sincronizar apagaria tudo que o bot tem no
            # Discord, em silêncio. O caso legítimo (quero zerar) vai
            # pela API direta, que é explícito.
            #
            # Distinto de "um escopo com zero comandos", que **apaga**
            # o remoto: esse é o comando órfão, que aparece pro usuário
            # como botão que não faz nada.
            _log.warning(
                "sync: nenhum comando registrado — nada sincronizado. Se a "
                "intenção era apagar tudo, use applications.delete_command()."
            )
            return SyncReport(aplicado=apply)

        app_id = await self._application_id()

        created: list[Entrada] = []
        updated: list[Entrada] = []
        deleted: list[Entrada] = []
        unchanged: list[Entrada] = []

        for escopo in escopos:
            locais = self._registry.for_scope(escopo)
            remotos = await self._api.list_commands(app_id, guild_id=escopo)

            acao, payloads = _diff(locais, remotos)
            for nome, a in acao.items():
                {
                    SyncAction.CREATED: created,
                    SyncAction.UPDATED: updated,
                    SyncAction.DELETED: deleted,
                    SyncAction.UNCHANGED: unchanged,
                }[a].append((escopo, nome))

            if apply and _tem_mudanca(acao):
                await self._api.bulk_overwrite_commands(app_id, payloads, guild_id=escopo)
                _log.info(
                    "sync %s: %d criado(s), %d atualizado(s), %d removido(s)",
                    _nome_escopo(escopo),
                    sum(1 for a in acao.values() if a is SyncAction.CREATED),
                    sum(1 for a in acao.values() if a is SyncAction.UPDATED),
                    sum(1 for a in acao.values() if a is SyncAction.DELETED),
                )

        report = SyncReport(
            created=tuple(created),
            updated=tuple(updated),
            deleted=tuple(deleted),
            unchanged=tuple(unchanged),
            scopes=escopos,
            aplicado=apply,
        )

        if verbose:
            self._imprime(report)

        return report

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    def _valida_tudo(self) -> None:
        """Valida **todas** as definições antes da primeira requisição.

        Um grupo sem subcommand derruba o sync inteiro, com o nome do
        grupo — não depois de já ter enviado a metade da lista. O
        Discord responderia 400 sem dizer qual dos vinte estava errado.
        """
        for instancia in self._registry:
            validate_definition(instancia.definition)

    async def _application_id(self) -> int:
        """O `application_id` vem da aplicação logada, não do token.

        Perguntar ao Discord é mais honesto que assumir `user.id` — é o
        mesmo raciocínio do `ApplicationsAPI.me()`."""
        if self._app_id is not None:
            return self._app_id

        app = await self._api.me()
        identificador = app.get("id")
        if identificador is None:
            raise ValueError(
                "GET /applications/@me não veio com 'id' — não há como "
                "descobrir o application_id para sincronizar"
            )
        self._app_id = int(identificador)
        return self._app_id

    def _imprime(self, report: SyncReport) -> None:
        if report.vazio:
            _log.info("sync: nenhuma mudança em %d escopo(s)", len(report.scopes))
            return

        _log.info("sync: %d mudança(s), aplicado=%s", report.mudancas, report.aplicado)
        for linha in report.linhas():
            _log.info("%s", linha)


def _tem_mudanca(acao: Mapping[str, SyncAction]) -> bool:
    return any(a is not SyncAction.UNCHANGED for a in acao.values())


def _nome_escopo(escopo: int | None) -> str:
    return "global" if escopo is None else f"guild {escopo}"


def _diff(
    locais: Iterable[Any], remotos: Iterable[ApplicationCommand]
) -> tuple[dict[str, SyncAction], list[dict[str, Any]]]:
    """Compara o local com o remoto, por `(type, name)`.

    O escopo já está filtrado antes de chegar aqui — dentro de um
    escopo, `(type, name)` identifica. É o `type` que evita o menu USER
    `ping` colidir com o `/ping`.
    """
    por_chave_local = {(int(i.type), i.name): i.definition for i in locais}
    por_chave_remota = {(int(c.type), c.name): c for c in remotos}

    acao: dict[str, SyncAction] = {}
    payloads: list[dict[str, Any]] = []

    for chave, definicao in sorted(por_chave_local.items()):
        rotulo = f"{definicao.name} ({ApplicationCommandType(chave[0]).name})"
        remoto = por_chave_remota.get(chave)

        if remoto is None:
            acao[rotulo] = SyncAction.CREATED
        elif _comparavel_remoto(remoto) != _comparavel_local(definicao):
            acao[rotulo] = SyncAction.UPDATED
        else:
            acao[rotulo] = SyncAction.UNCHANGED

        payloads.append(definicao.to_payload())

    for chave, comando in por_chave_remota.items():
        if chave not in por_chave_local:
            rotulo = f"{comando.name} ({ApplicationCommandType(chave[0]).name})"
            acao[rotulo] = SyncAction.DELETED

    return acao, payloads


def _comparavel_local(d: Any) -> dict[str, Any]:
    """Forma canônica do local, para comparação.

    `to_payload()` manda o que o Discord espera — incluindo `required`
    sempre. O remoto vem sem `required` quando é falso. Comparar os
    dois crus daria "atualizado" para sempre, e o `verbose` mentiria a
    cada boot.
    """
    return _canonico(d.to_payload())


def _comparavel_remoto(c: ApplicationCommand) -> dict[str, Any]:
    """Forma canônica do remoto, na mesma forma do local."""
    bruto: dict[str, Any] = {
        "name": c.name,
        "type": int(c.type),
        "description": c.description,
    }
    if c.options:
        bruto["options"] = [dict(o) for o in c.options]
    if c.default_member_permissions is not None:
        bruto["default_member_permissions"] = str(c.default_member_permissions)
    if c.dm_permission is not None:
        bruto["dm_permission"] = c.dm_permission
    if c.nsfw:
        bruto["nsfw"] = True
    if c.name_localizations:
        bruto["name_localizations"] = dict(c.name_localizations)
    if c.description_localizations:
        bruto["description_localizations"] = dict(c.description_localizations)
    return _canonico(bruto)


def _canonico(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normaliza opções recursivamente, preenchendo os defaults que o
    Discord omite.

    Sem isto, `required=False` local contra `required` ausente no
    remoto é uma diferença eterna — e o diff nunca diria "iguais".
    """
    saida: dict[str, Any] = {}
    for chave, valor in payload.items():
        if chave == "options" and isinstance(valor, (list, tuple)):
            saida[chave] = sorted(
                (_canonico(o) for o in valor if isinstance(o, Mapping)),
                key=lambda o: str(o.get("name", "")),
            )
        else:
            saida[chave] = valor
    saida.setdefault("required", False)
    saida.setdefault("description", "")
    return saida
