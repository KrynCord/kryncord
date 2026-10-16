# 0030 — `on_error` e `on_not_found` declarados no `@command`

## Contexto

`0026` §1 pôs os dois na assinatura do decorator:

```python
@command(
    name="ping",
    description="Responde com pong",
    middleware=...,
    on_error=...,
    on_not_found=...,
)
async def ping(ctx): ...
```

O Bloco 8 implementou exatamente isso: `create_command` grava
`instancia._on_error` e `instancia._on_not_found`, e os dois ganharam
propriedade de leitura na `CommandInstance`.

E aí um grep em `src/` inteiro por `\.on_error` / `\.on_not_found`
devolve **uma** ocorrência — `opcoes.on_error` em `client.py`. Ninguém
nunca leu `instancia.on_error` nem `instancia.on_not_found`.

O despacho usa só o que vem do `Options`:

```python
# interactions/dispatch.py
on_error = (_get(command_options, "on_error"),)
on_not_found = (_get(command_options, "on_not_found"),)
```

Ou seja: os dois parâmetros do decorator são configuração morta. Um
usuário que escreve `@command(..., on_error=meu_erro)` recebe silêncio
em cada falha — que é o mesmo sintoma que o `0028` usou para justificar
dar dono ao `CommandOptions.guilds`.

Os dois parâmetros, porém, não têm o mesmo problema.

### Só um deles tem casa

| Parâmetro | Existe um momento em que ele pode rodar? |
|---|---|
| `on_error` | **Sim.** O comando existe — é ele que falhou |
| `on_not_found` | **Não.** `dispatch_application_command` só chega ao `on_not_found` quando `instancia is None`; e ali não existe instância para ler |

E `on_not_found` tem um segundo problema, que é pior que o primeiro: a
`Options.on_not_found` significa "**este nome não existe**". Uma
instância só existe se o nome existir. Dar ao parâmetro do decorator um
significado diferente ("a rota **dentro** do comando não existe") seria
dois contratos para o mesmo nome, no mesmo objeto, na mesma opção.

As ideias concordam entre si e com o código: `on_not_found` aparece só
nos `Options` (`ideias/02` §decisão, `ideias/11` §5,
`ideias/exemplos/bot_configurado.py`), e o exemplo de decorator mais
próximo de produção (`ideias/02` §"E os decorators") mostra
`name`, `description`, `type` — nada de `on_not_found`.

## Decisão

### 1. `on_error` por comando passa a ser lido

```python
# commands/dispatch.py :: dispatch_application_command
alvo = instancia.on_error if instancia.on_error is not None else on_error
...
await _erro(exc, ctx, alvo)
```

A instância **vence** e o `Options` completa. É a mesma relação de
prioridade que o `0017` já estabeleceu para middleware local vs.
global: quem declarou no comando quer o tratamento do comando, e
quem não declarou herda o global. Inverter faria um `on_error` global
sobrescrever silenciosamente o que o autor do comando escreveu.

O default (nenhum dos dois) continua sendo o do `0026` §11: loga, e se
ainda dá tempo tenta uma efêmera.

### 2. `on_not_found` sai da superfície do decorator

Removido de `command()`, de `create_command()` e da `CommandInstance`
(`_on_not_found` + propriedade). O `on_not_found` continua existindo
nos dois `Options`, com a assinatura do `0029`.

Remover, e não deixar declarado-e-não-lido: um parâmetro que parece
funcionar e não funciona é pior que um parâmetro inexistente, e é
literalmente o argumento do `0028` §Consequências aplicado aqui.

## Consequências

- `@command(on_not_found=...)` passa a levantar `TypeError` na
  importação — erro na linha do decorator, que é onde toda validação
  deste módulo acontece. Não é quebra silenciosa: é a superfície
  deixando de prometer o que não entrega.
- `@command(on_error=...)` deixa de ser morto. Nenhum teste existente
  usava o parâmetro, então nada quebrou ao ligá-lo — e nenhum teste
  podia provar que ele funcionava, porque ele não funcionava.
- `CommandInstance.on_not_found` deixa de existir; `.on_error` passa a
  ser lido pelo despacho.
- `0026` §1 muda de redação: `on_not_found=` sai da lista do decorator.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Ligar os dois, dando ao `on_not_found` do comando a casa "subcomando não registrado" | Dois significados para o mesmo nome no mesmo objeto — quem ler `CommandOptions.on_not_found` e `command(on_not_found=)` vai assumir que são a mesma pergunta |
| Manter `on_not_found=` declarado e só não chamar | É o problema atual, escrito de propósito |
| Só documentar que não funciona | Um knob documentado como não-funcional continua sendo um knob que alguém vai ligar |
| Ligar `on_error` com o `Options` vencendo | Um erro global sobrescreveria o que o autor do comando escreveu, sem aviso |

## Parecer do conselho

| # | Contribuição |
|---|---|
| 19 Analista | O grep de uma ocorrência é o achado inteiro: dois parâmetros documentados, zero leitores |
| 01 Simplicidade | "`on_error` liga com duas linhas; `on_not_found` sai da assinatura. Não precisa de terceiro caminho." |
| 17 Crítico | Contestou remover o `on_not_found` — "é superfície quebrada, não ausente". Resposta venceu pela metade: quebrá-la na importação é transformar silêncio em traceback apontando a linha certa |
| 09 Testes | Nenhum teste existente usava os parâmetros, o que é a prova de que a cobertura não podia pegar — e de que a remoção não derruba nada |
| 06 Arquitetura | Dois significados para `on_not_found` (não existe o nome / não existe a rota) seriam dois contratos no mesmo objeto, e o nome não os distingue |
| 11 Idiomático | A prioridade instância → `Options` é a mesma da middleware local → global do `0017`; inverter seria uma segunda regra para a mesma pergunta |
| 18 Pragmático | Preferiu manter `on_not_found=` e logar um `DeprecationWarning`; não entrou porque deprecation warning em parâmetro que nunca funcionou anuncia um comportamento que ninguém teve |
| 20 Visionário | Propôs criar `RouteNotFound(DispatchError)` para dar casa ao parâmetro. Guardado: se um dia o "subcomando não registrado" precisar de tratamento próprio, é a exceção certa — mas ainda não tem caso concreto |

## Veredito do juiz: APROVADO

O juiz pediu que a **remoção** fosse registrada como mudança de
superfície em `0026` §1, e não só aqui: quem lê a decisão que criou o
parâmetro tem que achar a decisão que o retirou.

## Divergência preservada

O Participante 18 (Pragmático) defendia manter `on_not_found=` no
decorator com `DeprecationWarning`, para não quebrar ninguém. Não
entrou porque não há ninguém para não quebrar: o parâmetro não teve
release funcionando, e um warning sobre um comportamento que nunca
existiu é uma mensagem sem destinatário.

## Confiança: 84%
