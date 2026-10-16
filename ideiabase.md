# Bootstrap (/pt/docs/discord/bootstrap)





## Ponto de entrada [#ponto-de-entrada]

O arquivo `index.ts` da pasta `src` é o ponto de entrada deste projeto, é nele que a função <CodeSpan.Method identifier="bootstrap" /> é executada para ligar a aplicação de bot de discord.

```ts title="src/index.ts"
import { bootstrap } from "@constatic/base";

await bootstrap({ meta: import.meta });
```

Neste tópico você vai conferir algumas opções interessantes dessa função.

***

### Meta [#meta]

Essa opção deve receber o import.meta do arquivo atual, ao executar o projeto em desenvolvimento, o diretório de import.meta será `src`, mas quando o projeto for buildado ele será `build`.
Essa opção é importante para que os arquivos da pasta discord possam ser importados antes do bot iniciar.

### Modules [#modules]

Você pode passar um array de [padrões glob](https://en.wikipedia.org/wiki/Glob_\(programming\)) relativos à pasta atual. Todos os arquivos arquivos e diretórios encontrados neste padrão, serão importados antes do bot iniciar.

```ts title="src/index.ts"
await bootstrap({ 
    meta: import.meta,
    modules: [
        "./MyCommands/**", 
        "./alt/events", 
        "./tools/**/*.mod.{ts,js}"
    ]
});
```

Com isso você pode criar `comandos`, `eventos` e `responders` dentro desses diretórios e eles serão carregados antes do bot iniciar.

<Callout type="info">
  Também tem a possibilidade de carregar arquivos com *side effects*, assim podendo registrar variáveis globais, alterar protótipos de objetos existentes e entre outros.
</Callout>

***

### Logs de carregamento (loadLogs) [#logs-de-carregamento-loadlogs]

É possível desabilitar as logs de carregamento das estruturas dessa base definindo `falso` na opção <CodeSpan.Prop identifier="loadLogs" /> da função <CodeSpan.Method identifier="bootstrap" />.

```ts title="src/index.ts"
await bootstrap({ 
    meta: import.meta,
    loadLogs: false
});
```

***

### Antes de carregar (beforeLoad) [#antes-de-carregar-beforeload]

Você você pode executar um código antes dos diretórios serem carregados e recebe o <CodeSpan.Class identifier="Client" /> antes de ficar online (ready).

```ts title="src/index.ts"
await bootstrap({ 
    meta: import.meta,
    async beforeLoad(client) {
        console.log(client.application); // null;
        console.log("Isso ocorre antes do carregamento dos diretórios")
    },
});
```

***
# Criadores (/pt/docs/discord/creators)





Nesta base, para criar comandos e sistemas você deve utilizar as funções criadoras, que são <CodeSpan.Method identifier="createCommand" />, <CodeSpan.Method identifier="createEvent" /> e <CodeSpan.Method identifier="createResponder" />.

Ao executar essas funções passando os dados da estruturas respectivas, elas serão criadas e registradas.

Você pode definir algumas opções no arquivo `index` da pasta `discord`, veja:

```ts title="src/discord/index.ts"
// [!code word:setupCreators]
import { setupCreators } from "@constatic/base";

export const { createCommand, createEvent, createResponder } = setupCreators();
```

Essa função recebe opções e retorna os criadores de comandos, eventos e responders para você utilizar. Exportando já esse retorno você pode importar eles a qualquer momento pelo atalho da base:

```ts
import { createCommand, createEvent, createResponder } from "#base";
```

## Opções de comandos [#command-options]

Você pode definir algumas opções de comandos na função <CodeSpan.Method identifier="setupCreators" />:

<Tabs items="[&#x22;Permissões padrões&#x22;, &#x22;Guildas&#x22;, &#x22;middleware&#x22;, &#x22;onError&#x22;, &#x22;onNotFound&#x22;, &#x22;verbose&#x22;]">
  <Tab id="commands-default-permissions" value="Permissões padrões">
    Defina quais serão as permissões padrões de todos os comandos, caso não seja definida nenhuma com a opção <CodeSpan.Prop identifier="defaultMemberPermissions" /> (É o mesmo array de permissões do comando).

    ```ts
    /* ... */ setupCreators({
        commands: {
            defaultMemberPermissions: ["SendMessages", "Connect"]
        },
    });
    ```

    Dessa forma, ao criar um comando e não definir nenhuma permissão padrão de membro, o que você definiu na função <CodeSpan.Method identifier="setupCreators" />, será o padrão de todos os comandos.

    ```ts title="command.ts"
    createCommand({
        name: "ping",
        description: "Responde com pong",
        type: ApplicationCommandType.ChatInput,
        // defaultMemberPermissions: [] <-- Não foi definido!
        // Mas por padrão será registrado na aplicação com ["SendMessages", "Connect"]
        async run(interaction){
            // ...
        }
    })
    ```
  </Tab>

  <Tab id="commands-guilds" value="Guildas">
    Você pode definir vários IDs de guildas que deseja registrar os comandos do seu bot com a opção `guilds`.

    ```ts
    import { env } from "#env";

    /* ... */ setupCreators({
        commands: {
            guilds: [env.MAIN_GUILD_ID, "537817462272557057"]
        },
    });
    ```

    Assim, ao invés de registrar os comandos globalmente na aplicação, eles serão registrados apenas nas guildas, cujo os ids foram passados para essa opção.
  </Tab>

  <Tab id="commands-middleware" value="middleware">
    Você pode definir uma função <CodeSpan.Method identifier="middleware" /> que será executada antes da função <CodeSpan.Method identifier="run" /> dos comandos

    ```ts
    /* ... */ setupCreators({
        commands: {
            async middleware(interaction){
                console.log("Comando executado:", interaction.commandName);
            }
        },
    });
    ```

    Você pode fazer muita coisa com isso, como exibir logs padronizados para todos os comandos executados, injetar informações adicionais na interação, ou até mesmo bloquear a execução com base em checagens.

    Você pode executar a função <CodeSpan.Method identifier="block" /> para bloquear a execução dos comandos.

    ```ts
    /* ... */ setupCreators({
        commands: {
            async middleware(interaction, block){
                if (blockedUsers.includes(interaction.user.id)){
                    interaction.reply({ content: "Você não pode usar nenhum comando!" });
                    block();
                    return;
                }
            }
        },
    });
    ```
  </Tab>

  <Tab id="commands-onerror" value="onError">
    É possível definir um manipulador de erros customizado para comandos com a função `onError`

    ```ts
    /* ... */ setupCreators({
        commands: {
            async onError(error, interaction){
                // ...
            }
        },
    });
    ```

    Você pode verificar qual é o tipo de erro e escolher entre enviar ou não, mensagens customizadas.

    <Callout type="danger">
      É extremamente importante usar `await` em Promises quando o seu run for `async`, para que o manipulador de erros de comandos possa capturar corretamente.
    </Callout>

    ```ts
    // [!code word:await]
    createCommand({
        name: "ping",
        description: "Responde com pong",
        async run(interaction){
            await interaction.deferReply({ flags: ["Ephemeral"], });

            const data = await dbOperation();

            await interaction.editReply({ content: `Dados: ${data.toString()}` });
        }
    })
    ```
  </Tab>

  <Tab id="commands-onnotfound" value="onNotFound">
    Se por algum motivo não for encontrado nenhum manipulador para o comando, a função `onNotFound` será chamada.

    ```ts
    /* ... */ setupCreators({
        commands: {
            async onNotFound(interaction){
                interaction.reply({ flags: ["Ephemeral"],, 
                    content: "Comando não encontrado. Contate a equipe!"
                });
            }
        },
    });
    ```
  </Tab>

  <Tab id="commands-verboose" value="verbose">
    Essa opção faz com que as logs de registro de comandos sejam mais detalhadas, dessa maneira você pode ter certeza de que seus comandos foram registrados pois isso exibe a resposta direta da api

    ```ts
    /* ... */ setupCreators({
        commands: {
            verboose: true
        },
    });
    ```

    Veja o exemplo abaixo com os comandos que vem por padrão:

    ```bash
    ● Awes online ✓
    └ 2 commands successfully registered globally!
      └ {/} 1342179401697333281 CREATED ping > Awes application > created at: 1:01:45 PM
      └ {/} 1342179401252470856 CREATED counter > Awes application > created at: 1:01:45 PM
    ```

    A resposta exibe o id do comando na aplicação ou guilda, o nome dele e o horario em que foi criado
  </Tab>
</Tabs>

## Opções de Responders [#responder-options]

Você pode definir algumas opções de responders na função <CodeSpan.Method identifier="setupCreators" />:

<Tabs items="[&#x22;Middleware&#x22;, &#x22;onError&#x22;, &#x22;onNotFound&#x22;]">
  <Tab id="responders-middleware" value="Middleware">
    Você pode definir uma função <CodeSpan.Method identifier="middleware" /> que será executada antes da função <CodeSpan.Method identifier="run" /> dos responders

    ```ts
    /* ... */ setupCreators({
        responders: {
            async middleware(interaction, _block, params){
                console.log("Comando executado:", interaction.customId);
                console.log("Parâmetros:", params);
            }
        },
    });
    ```

    Assim como nos comandos, você pode fazer muita coisa com isso, como exibir logs padronizados para todos os responders executados, injetar informações adicionais na interação, ou até mesmo bloquear a execução com base em checagens.

    Você pode executar a função <CodeSpan.Method identifier="block" /> para bloquear a execução dos responders.

    ```ts
    /* ... */ setupCreators({
        responders: {
            async middleware(interaction, block){
                if (interaction.isButton() && blockedUsers.includes(interaction.user.id)){
                    interaction.reply({ content: "Você não pode clicar em nenhum botão!" });
                    block();
                    return;
                }
            }
        },
    });
    ```
  </Tab>

  <Tab id="responders-onerror" value="onError">
    É possível definir um manipulador de erros customizado para responders com a função `onError`

    ```ts
    /* ... */ setupCreators({
        commands: {
            async onError(error, interaction){
                // ...
            }
        },
    });
    ```

    Você pode verificar qual é o tipo de erro e escolher entre enviar ou não, mensagens customizadas.

    <Callout type="danger">
      É extremamente importante usar `await` em Promises quando o seu run for `async`, para que o manipulador de erros de responders possa capturar corretamente.
    </Callout>

    ```ts
    // [!code word:await]
    createResponder({
        customId: "data/refresh",
        types: [ResponderType.Button], cache: "cached",
        async run(interaction){
            await interaction.deferUpdate();

            const data = await dbOperation();

            await interaction.followUp({ 
                flags: ["Ephemeral"],, content: `Dados: ${data.toString()}` 
            });
        }
    })
    ```
  </Tab>

  <Tab id="responders-verboose" value="onNotFound">
    Se não for encontrado nenhum manipulador para o componente ou modal, a função `onNotFound` será chamada.

    ```ts
    /* ... */ setupCreators({
        responders: {
            async onNotFound(interaction){
                interaction.reply({ flags: ["Ephemeral"],, 
                    content: "Isso não foi configurado ainda. Contate a equipe!"
                });
            }
        },
    });
    ```

    <Callout type="danger">
      Tome cuidado! Se você usar coletores de componentes ou modais em algum comando, essa função ainda será chamada, pois ela busca um manipulador criado com a função <CodeSpan.Method identifier="createResponder" />. Então é importante verificar se a interação já foi respondida ou aguardar um pequeno tempo antes de responder de fato.
    </Callout>
  </Tab>
</Tabs>

## Opções de Eventos [#event-options]

Você pode definir algumas opções de eventos na função <CodeSpan.Method identifier="setupCreators" />:

<Tabs items="[&#x22;Middleware&#x22;, &#x22;onError&#x22;]">
  <Tab id="events-middleware" value="Middleware">
    Você pode definir uma função <CodeSpan.Method identifier="middleware" /> que será executada antes da função <CodeSpan.Method identifier="run" /> dos eventos

    ```ts
    /* ... */ setupCreators({
        events: {
            async middleware(event){
                console.log("Evento", event.name, "emitido");
            }
        },
    });
    ```

    Assim como nos comandos e responders, você pode fazer muita coisa com isso, como exibir logs padronizados para todos os eventos executados, injetar informações adicionais nos argumentos de eventos específicos, ou até mesmo bloquear a execução com base em checagens.

    <Callout type="info">
      No primeiro argumento, é recebido um objeto com os dados do evento, onde <CodeSpan.Prop identifier="name" /> é o nome do evento emitido e <CodeSpan.Prop identifier="args" /> são os argumentos desse evento, então verificando qual é o nome do evento, a tipagem dos argumentos é definida automaticamente:

      ```ts
      /* ... */ setupCreators({
          events: {
              async middleware(event) {
                  if (event.name === "guildMemberUpdate"){
                      const [oldMember, newMember] = event.args;
                      // ...
                      return;
                  }
                  if (event.name === "guildAuditLogEntryCreate"){
                      const [entry, guild] = event.args;
                      // ...
                      return;
                  }
                  if (event.name === "messageCreate"){
                      const [message] = event.args;
                      // ...
                      return;
                  }
              },
          },
      });
      ```
    </Callout>

    Você pode executar a função <CodeSpan.Method identifier="block" /> para bloquear a execução dos eventos.

    ```ts
    /* ... */ setupCreators({
        events: {
            async middleware(event, block){
                if (event.name === "messageDelete"){
                    const [message] = event.args;
                    if (message.inGuild() && message.author.id == message.guild.id){
                        block();
                        return;
                    }
                }
            }
        },
    });
    ```

    No caso dos eventos também é possível passar tags como argumento da função block, dessa maneira, você pode ter 3 eventos do mesmo tipo, por exemplo <CodeSpan.String content="messageCreate" />, mas bloquear apenas aqueles com as tags previamente definidas:

    <CodeBlockTabs defaultValue="Eventos">
      <CodeBlockTabsList>
        <CodeBlockTabsTrigger value="Eventos">
          Eventos
        </CodeBlockTabsTrigger>

        <CodeBlockTabsTrigger value="Middleware">
          Middleware
        </CodeBlockTabsTrigger>

        <CodeBlockTabsTrigger value="Funções utilitárias">
          Funções utilitárias
        </CodeBlockTabsTrigger>
      </CodeBlockTabsList>

      <CodeBlockTab value="Eventos">
        ```ts
        createEvent({
            name: "Morning workflow",
            event: "messageCreate",
            tags: ["morning"],
            async run(message) {
                // ...
            },
        });

        createEvent({
            name: "Night workflow",
            event: "messageCreate",
            tags: ["night"],
            async run(message) {
                // ...
            },
        });

        createEvent({
            name: "Messages Workflow",
            event: "messageCreate",
            async run(message) {
                // ...
            },
        });
        ```
      </CodeBlockTab>

      <CodeBlockTab value="Middleware">
        ```ts
        /* ... */ setupCreators({
            events: {
                async middleware(event, block){
                    if (event.name === "messageCreate"){
                        if (!isMorning()){
                            block("morning");
                            return;
                        }
                        if (!isNight()){
                            block("night");
                            return;
                        }
                    }
                }
            },
        });
        ```
      </CodeBlockTab>

      <CodeBlockTab value="Funções utilitárias">
        ```ts
        function isMorning(): boolean {
            const currentHour = new Date().getHours();
            return currentHour >= 6 && currentHour < 12;
        }
        function isNight(): boolean {
            const currentHour = new Date().getHours();
            return currentHour >= 20 || currentHour < 6;
        }
        ```
      </CodeBlockTab>
    </CodeBlockTabs>

    Você pode passar quantas tags quiser para função <CodeSpan.Method identifier="block" />

    ```ts
    // ...
    block("morning", "night", "foo", "bar", "baz")
    // ...
    ```

    Todos os eventos que conter alguma das tags passadas como argumento da função block, não serão executados
  </Tab>

  <Tab id="events-onerror" value="onError">
    É possível definir um manipulador de erros customizado para eventos com a função `onError`

    ```ts
    /* ... */ setupCreators({
        events: {
            async onError(error, event){
                // ...
            }
        },
    });
    ```

    Você pode verificar qual é o tipo de erro e escolher entre enviar ou não, mensagens customizadas.

    <Callout type="danger">
      É extremamente importante usar `await` em Promises quando o seu run for `async`, para que o manipulador de erros de eventos possa capturar corretamente.
    </Callout>

    ```ts
    // [!code word:await]
    createEvent({
        name: "Register workflow",
        event: "guildMemberAdd",
        async run(member) {
            const document = await db.members.create({
                id: member.id,
                username: member.user.username,
                guildId: member.guild.id
            });
            // ...
        },
    })
    ```
  </Tab>
</Tabs>
# Commandos de barra (/pt/docs/discord/commands/slash)





# Criando comandos de barra [#criando-comandos-de-barra]

<Callout type="success">
  É possível definir algumas opções para os comandos na função <CodeSpan.Method identifier="setupCreators" />!

  [Veja mais detalhes na página sobre as funções criadoras](/docs/discord/creators#command-options)
</Callout>

Antes de tudo, importe a função <CodeSpan.Method identifier="createCommand" /> da base e <CodeSpan.Enum identifier="ApplicationCommandType" /> do `discord.js`

```ts title="ping.ts"
import { createCommand } from "#base"
import { ApplicationCommandType } from "discord.js";
```

<Callout type="info">
  Veja [convenções](/docs/discord/conventions/structure#pasta-discord) para criar seus comandos
</Callout>

Para criar um comando de barra, você tem que definir o `nome`, a `descrição` e o `tipo`

```ts title="ping.ts"
createCommand({
    name: "ping",
    description: "Responde com pong",
    type: ApplicationCommandType.ChatInput,
    async run(interaction) {
        await interaction.reply({ 
            flags: ["Ephemeral"], 
            content: "Pong" 
        });
    },
});
```

<Callout type="danger">
  Nomes de comandos de barra (`/`) e de opções de comandos não podem ser strings vazias, não podem conter caractéres especiais, letras maiúsculas ou espaços
</Callout>

# Definindo opções de comando [#definindo-opções-de-comando]

Você pode definir `opções`, `sub comandos` e `grupos` também.

```ts title="manage.ts"
import { createCommand } from "#base";
import { ApplicationCommandOptionType, ApplicationCommandType } from "discord.js";

createCommand({
    name: "gerenciar",
    description: "Comando de gerenciar",
    type: ApplicationCommandType.ChatInput,
    options: [ // [!code highlight]
        { // [!code highlight]
            name: "usuários", // [!code highlight] 
            description: "Gerenciar usuários", // [!code highlight]
            type: ApplicationCommandOptionType.Subcommand // [!code highlight]
            options: [ // [!code highlight]
                { // [!code highlight] 
                    name: "usuário", // [!code highlight]
                    description: "Selecione o usuário", // [!code highlight]
                    type: ApplicationCommandOptionType.User // [!code highlight]
                    required // [!code highlight]
                } // [!code highlight]
            ], // [!code highlight]
        } // [!code highlight]
    ], // [!code highlight]
    async run(interaction) {
        const { options } = interaction;

        switch(options.getSubcommand(true)){
            case "usuários":{
                const user = options.getUser("usuário", true);
                await interaction.reply({ 
                    flags: ["Ephemeral"], 
                    content: `${user} managed` 
                })
                return;
            }
        }
    },
});
```

# Global [#global]

A opção <CodeSpan.Prop identifier="global" /> nos comandos é útil quando você quer que o comando seja registrado na aplicação ao invés da guilda. Só é necessário quando IDs de guildas são definidos na função [setupCreators](/docs/discord/creators/#commandoptions)

O código abaixo faz com que os comandos sejam registrados apenas nas guildas válidas listadas no array:

```ts title="src/discord/index.ts"
import { setupCreators } from "@constatic/base";
import { env } from "#env";

export const { createCommand, createEvent, createResponder } = setupCreators({
    commands: {
        guilds: [
            env.MAIN_GUILD_ID,
            env.DEV_GUILD_ID,
            env.TEST_GUILD_ID,
        ]
    }
});
```

Agora veja este código onde alguns comandos são criados:

```ts
createCommand({
	name: "configurações",
	description: "Comando de configurações do servidor",
	async run(interaction){
		// ...
	}
});

createCommand({
	name: "gerenciar",
	description: "Comando para gerenciar membros, canais e cargos",
	async run(interaction){
		// ...
	}
});

createCommand({
	name: "informações",
	description: "Exibe informações do bot",
	global: true, // [!code highlight]
	async run(interaction){
		// ...
	}
});
```

Os comandos `configurações` e `gerenciar` serão registrados nas guildas definidas na função <CodeSpan.Method identifier="setupCreators" />, mas o comando `informações` será registrado globalmente na aplicação, assim estando disponível em qualquer guilda.
# Modularização (/pt/docs/discord/commands/modularization)





<Callout type="warn">
  Este é um recurso exclusivo de [comandos de barra!](/docs/discord/commands/slash)
</Callout>

# Como modularizar [#como-modularizar]

Conforme vamos desenvolvendo sistemas para o nosso bot, mais comandos serão necessários. A melhor forma de manter os comandos intuitívos, é usando grupos e sub comandos, mas isso pode trazer um pequeno problema para o código, veja o exemplo abaixo:

```ts title="src/discord/commands/manage.ts"
import { createCommand } from "#base";
import { ApplicationCommandOptionType, CategoryChannelType, ChannelType, codeBlock, PermissionFlagsBits, PermissionsString } from "discord.js";

const guildChannelTypes = [
    ChannelType.GuildAnnouncement,
    ChannelType.GuildForum,
    ChannelType.GuildText,
    ChannelType.GuildVoice,
] as const;

createCommand({
    name: "manage",
    description: "Manage command",
    defaultMemberPermissions: ["Administrator"],
    dmPermission: false,
    options: [
        {
            name: "roles",
            description: "Manage roles",
            type: ApplicationCommandOptionType.SubcommandGroup,
            options: [
                {
                    name: "create",
                    description: "Create new role",
                    type: ApplicationCommandOptionType.Subcommand,
                    options: [
                        {
                            name: "name",
                            description: "Role name",
                            type: ApplicationCommandOptionType.String,
                            required: true,
                        },
                    ],
                },
                {
                    name: "permissions",
                    description: "Change role permissions",
                    type: ApplicationCommandOptionType.Subcommand,
                    options: [
                        {
                            name: "role",
                            description: "Select the role",
                            type: ApplicationCommandOptionType.Role,
                            required: true,
                        },
                        {
                            name: "action",
                            description: "Select the action",
                            type: ApplicationCommandOptionType.String,
                            choices: [
                                { name: "Add", value: "add" },
                                { name: "Remove", value: "remove" },
                            ],
                            required: true,
                        },
                        {
                            name: "permission",
                            description: "Select the permission",
                            type: ApplicationCommandOptionType.String,
                            choices: Object.keys(PermissionFlagsBits)
                                .map(value => ({ name: value, value })),
                            required: true,
                        },
                    ],
                },
                {
                    name: "delete",
                    description: "Delete a role",
                    type: ApplicationCommandOptionType.Subcommand,
                    options: [
                        {
                            name: "role",
                            description: "Select the role",
                            type: ApplicationCommandOptionType.Role,
                            required: true,
                        },
                    ],
                }
            ]
        },
        {
            name: "channels",
            description: "Manage channels",
            type: ApplicationCommandOptionType.SubcommandGroup,
            options: [
                {
                    name: "create",
                    description: "Create new channel",
                    type: ApplicationCommandOptionType.Subcommand,
                    options: [
                        {
                            name: "name",
                            description: "Channel name",
                            type: ApplicationCommandOptionType.String,
                            required: true,
                        },
                        {
                            name: "category",
                            description: "Select a channel category",
                            type: ApplicationCommandOptionType.Channel,
                            channelTypes: [ChannelType.GuildCategory]
                        },
                        {
                            name: "type",
                            type: ApplicationCommandOptionType.Integer,
                            choices: [
                                { name: "Text", value: ChannelType.GuildText },
                                { name: "Announcement", value: ChannelType.GuildAnnouncement },
                                { name: "Forum", value: ChannelType.GuildForum },
                                { name: "Voice", value: ChannelType.GuildVoice },
                            ]
                        }
                    ],
                },
                {
                    name: "move",
                    description: "Change channel category",
                    type: ApplicationCommandOptionType.Subcommand,
                    options: [
                        {
                            name: "channel",
                            description: "Select the channel",
                            type: ApplicationCommandOptionType.Channel,
                            channelTypes: guildChannelTypes,
                            required: true,
                        },
                        {
                            name: "category",
                            description: "Select the new category",
                            type: ApplicationCommandOptionType.Channel,
                            channelTypes: [ChannelType.GuildCategory],
                            required: true,
                        },
                    ],
                },
                {
                    name: "delete",
                    description: "Delete a channel",
                    type: ApplicationCommandOptionType.Subcommand,
                    options: [
                        {
                            name: "channel",
                            description: "Select the channel",
                            type: ApplicationCommandOptionType.Channel,
                            channelTypes: guildChannelTypes,
                            required: true,
                        },
                    ],
                }
            ]
        }
    ],
    async run(interaction) {
        const { options, guild } = interaction;

        const group = options.getSubcommandGroup();
        const subcommand = options.getSubcommand();

        switch (group) {
            case "roles": {
                switch (subcommand) {
                    case "create": {
                        const name = options.getString("name", true);

                        await interaction.reply({
                            flags: ["Ephemeral"],
                            content: "Creating role..."
                        });

                        await guild.roles.create({ name })
                            .then(role => interaction.editReply({
                                content: `Role created ${role}`
                            }))
                            .catch(err => interaction.editReply({
                                content: `Error: ${codeBlock(err)}`
                            }));
                        return;
                    }
                    case "permissions": {
                        const role = options.getRole("role", true);
                        const action = options.getString("action", true) as "add" | "remove";
                        const permission = options.getString("permission") as PermissionsString;

                        await interaction.reply({
                            flags: ["Ephemeral"],
                            content: "Update permissions..."
                        });

                        const permissions = role.permissions[action](permission).toArray();

                        role.edit({ permissions })
                            .then(role => interaction.editReply({
                                content: `${action} permissions: ${role}`
                            }))
                            .catch(err => interaction.editReply({
                                content: `Error: ${codeBlock(err)}`
                            }));
                        return;
                    }
                    case "delete": {
                        const role = options.getRole("role", true);

                        await interaction.reply({
                            flags: ["Ephemeral"],
                            content: "Deleting role..."
                        });

                        await role.delete()
                            .then(() => interaction.editReply({
                                content: "Channel deleted!"
                            }))
                            .catch(err => interaction.editReply({
                                content: `Error: ${codeBlock(err)}`
                            }));
                        return;
                    }
                }
                return;
            }
            case "channels": {
                switch (subcommand) {
                    case "create": {
                        const name = options.getString("name", true);
                        const parent = options.getChannel("category", false, [ChannelType.GuildCategory]);
                        const type = options.getInteger("type") as CategoryChannelType;

                        await interaction.reply({
                            flags: ["Ephemeral"],
                            content: "Creating channel..."
                        });

                        await guild.channels.create({ name, type, parent })
                            .then(channel => interaction.editReply({
                                content: `Channel created ${channel.url}`
                            }))
                            .catch(err => interaction.editReply({
                                content: `Error: ${codeBlock(err)}`
                            }));
                        return;
                    }
                    case "move": {
                        const channel = options.getChannel("channel", true, guildChannelTypes);
                        const parent = options.getChannel("category", true, [ChannelType.GuildCategory]);

                        await interaction.reply({
                            flags: ["Ephemeral"],
                            content: "Moving channel..."
                        });

                        await channel.setParent(parent)
                            .then(channel => interaction.editReply({
                                content: `Channel moved ${channel.url}`
                            }))
                            .catch(err => interaction.editReply({
                                content: `Error: ${codeBlock(err)}`
                            }));
                        return;
                    }
                    case "delete": {
                        const channel = options.getChannel("channel", true, guildChannelTypes);

                        await interaction.reply({
                            flags: ["Ephemeral"],
                            content: "Deleting channel..."
                        });

                        await channel.delete()
                            .then(() => interaction.editReply({
                                content: "Channel deleted!"
                            }))
                            .catch(err => interaction.editReply({
                                content: `Error: ${codeBlock(err)}`
                            }));
                        return;
                    }
                }
                return;
            }
        }
    },
});
```

<Callout type="warn">
  Mesmo que bem simples, este comando tem mais de 200 linhas de código. Imagine um comando real com mais complexidade, verificações, transformações, interatividade, ficaria muito maior. Isso pode ser ruim ao longo do tempo se você deseja manter seu projeto e atualizar sempre.
</Callout>

A função <CodeSpan.Method identifier="createCommand" /> retorna um `CommandInstance` que contém dois métodos especiais: <CodeSpan.Method identifier="group" /> e <CodeSpan.Method identifier="subcommand" />. Como você pode imaginar isso serve para criar grupos e sub comandos:

```ts title="src/discord/commands/manage.ts"
const command = createCommand({
    /* ... */                     
});

command.group({
    /* ... */
})

command.subcommand({
    /* ... */
})
```

Com isso em mente, vamos quebrar aquele comando gigante e separar em arquivos diferentes:

<Callout type="hint">
  É recomendado criar uma pasta exclusiva para o seu comando gigante! Neste exemplo vamos criar a pasta **manage**. O caminho no projeto ficaria em `./src/discord/commands/manage/`

  <Files>
    <Folder name="src">
      <Folder name="discord">
        <Folder name="commands">
          <Folder name="manage">
            <File name="command.ts" icon="<TsIcon />" />
          </Folder>
        </Folder>
      </Folder>
    </Folder>
  </Files>
</Callout>

```ts title="src/discord/commands/manage/command.ts"
import { createCommand } from "#base";

export default createCommand({
    name: "manage",
    description: "Manage command",
    defaultMemberPermissions: ["Administrator"],
    dmPermission: false,
});
```

Agora dentro da pasta **manage** vamos criar outras pastas para os grupos de sub comandos. A estrutura deve ficar parecida com isso:

<Files>
  <Folder name="manage">
    <Folder name="channels">
      <File name="create.ts" icon="<TsIcon />" />

      <File name="delete.ts" icon="<TsIcon />" />

      <File name="group.ts" icon="<TsIcon />" />

      <File name="move.ts" icon="<TsIcon />" />
    </Folder>

    <Folder name="roles">
      <File name="create.ts" icon="<TsIcon />" />

      <File name="delete.ts" icon="<TsIcon />" />

      <File name="group.ts" icon="<TsIcon />" />

      <File name="permissions.ts" icon="<TsIcon />" />
    </Folder>

    <File name="command.ts" icon="<TsIcon />" />
  </Folder>
</Files>

Como exportamos o retorno da função <CodeSpan.Method identifier="createCommand" /> usando `export default`, podemos importar nos arquivos `group.ts` das pastas **channels** e **roles** para definir os grupos de sub comandos:

<Tabs items="[&#x22;channels&#x22;, &#x22;roles&#x22;]">
  <Tab value="channels">
    ```ts title="manage/channels/group.ts"
    import { ChannelType } from "discord.js";
    import command from "../command.js";

    // [!code word:guildChannelTypes]
    export const guildChannelTypes = [ // [!code highlight]
        ChannelType.GuildAnnouncement,  // [!code highlight]
        ChannelType.GuildForum,  // [!code highlight]
        ChannelType.GuildText,  // [!code highlight]
        ChannelType.GuildVoice,  // [!code highlight]
    ] as const;  // [!code highlight]

    export default command.group({
        name: "channels",
        description: "Manage channels",
    });
    ```

    Podemos exportar variáveis que serão usadas nos sub comandos desse grupo também
  </Tab>

  <Tab value="roles">
    ```ts title="manage/roles/group.ts"
    import command from "../command.js";

    export default command.group({
        name: "roles",
        description: "Manage roles"
    });
    ```
  </Tab>
</Tabs>

Agora basta criar um arquivo para cada sub comando e o seu código já vai estar modularizado:

<Tabs items="[&#x22;channels&#x22;, &#x22;roles&#x22;]">
  <Tab value="channels">
    Sub comandos para o grupo **channels**:

    <Tabs items="[&#x22;create&#x22;, &#x22;delete&#x22;, &#x22;move&#x22;]">
      <Tab value="create">
        ```ts title="manage/channels/create.ts"
        import { ApplicationCommandOptionType, CategoryChannelType, ChannelType, codeBlock } from "discord.js";
        import group from "./group.js";

        group.subcommand({
            name: "create",
            description: "Create new channel",
            options: [
                {
                    name: "name",
                    description: "Channel name",
                    type: ApplicationCommandOptionType.String,
                    required: true,
                },
                {
                    name: "category",
                    description: "Select a channel category",
                    type: ApplicationCommandOptionType.Channel,
                    channelTypes: [ChannelType.GuildCategory]
                },
                {
                    name: "type",
                    type: ApplicationCommandOptionType.Integer,
                    choices: [
                        { name: "Text", value: ChannelType.GuildText },
                        { name: "Announcement", value: ChannelType.GuildAnnouncement },
                        { name: "Forum", value: ChannelType.GuildForum },
                        { name: "Voice", value: ChannelType.GuildVoice },
                    ]
                }
            ],
            async run(interaction) {
                const { options, guild } = interaction;

                const name = options.getString("name", true);
                const parent = options.getChannel("category", false, [ChannelType.GuildCategory]);
                const type = options.getInteger("type") as CategoryChannelType;

                await interaction.reply({
                    flags: ["Ephemeral"],
                    content: "Creating channel..."
                });

                await guild.channels.create({ name, type, parent })
                    .then(channel => interaction.editReply({
                        content: `Channel created ${channel.url}`
                    }))
                    .catch(err => interaction.editReply({
                        content: `Error: ${codeBlock(err)}`
                    }));
            },
        })
        ```
      </Tab>

      <Tab value="delete">
        ```ts title="manage/channels/delete.ts"
        import { ApplicationCommandOptionType, codeBlock } from "discord.js";
        import group, { guildChannelTypes } from "./group.js";

        group.subcommand({
            name: "delete",
            description: "Delete a channel",
            options: [
                {
                    name: "channel",
                    description: "Select the channel",
                    type: ApplicationCommandOptionType.Channel,
                    channelTypes: guildChannelTypes,
                    required: true,
                },
            ],
            async run(interaction) {
                const { options } = interaction;

                const channel = options.getChannel("channel", true, guildChannelTypes);

                await interaction.reply({
                    flags: ["Ephemeral"],
                    content: "Deleting channel..."
                });

                await channel.delete()
                    .then(() => interaction.editReply({
                        content: "Channel deleted!"
                    }))
                    .catch(err => interaction.editReply({
                        content: `Error: ${codeBlock(err)}`
                    }));
            },
        })
        ```
      </Tab>

      <Tab value="move">
        ```ts title="manage/channels/move.ts"
        import { ApplicationCommandOptionType, ChannelType, codeBlock } from "discord.js";
        import group, { guildChannelTypes } from "./group.js";

        group.subcommand({
            name: "move",
            description: "Change channel category",
            options: [
                {
                    name: "channel",
                    description: "Select the channel",
                    type: ApplicationCommandOptionType.Channel,
                    channelTypes: guildChannelTypes,
                    required: true,
                },
                {
                    name: "category",
                    description: "Select the new category",
                    type: ApplicationCommandOptionType.Channel,
                    channelTypes: [ChannelType.GuildCategory],
                    required: true,
                },
            ],
            async run(interaction) {
                const { options } = interaction;

                const channel = options.getChannel("channel", true, guildChannelTypes);
                const parent = options.getChannel("category", true, [ChannelType.GuildCategory]);

                await interaction.reply({
                    flags: ["Ephemeral"],
                    content: "Moving channel..."
                });

                await channel.setParent(parent)
                    .then(channel => interaction.editReply({
                        content: `Channel moved ${channel.url}`
                    }))
                    .catch(err => interaction.editReply({
                        content: `Error: ${codeBlock(err)}`
                    }));
            },
        })
        ```
      </Tab>
    </Tabs>
  </Tab>

  <Tab value="roles">
    Sub comandos para o grupo **roles**:

    <Tabs items="[&#x22;create&#x22;, &#x22;delete&#x22;, &#x22;permissions&#x22;]">
      <Tab value="create">
        ```ts title="manage/roles/create.ts"
        import { ApplicationCommandOptionType, codeBlock } from "discord.js";
        import group from "./group.js";

        group.subcommand({
            name: "create",
            description: "Create new role",
            options: [
                {
                    name: "name",
                    description: "Role name",
                    type: ApplicationCommandOptionType.String,
                    required: true,
                },
            ],
            async run(interaction) {
                const { options, guild } = interaction;

                const name = options.getString("name", true);

                await interaction.reply({
                    flags: ["Ephemeral"],
                    content: "Creating role..."
                });

                await guild.roles.create({ name })
                    .then(role => interaction.editReply({
                        content: `Role created ${role}`
                    }))
                    .catch(err => interaction.editReply({
                        content: `Error: ${codeBlock(err)}`
                    }));
            },
        })
        ```
      </Tab>

      <Tab value="delete">
        ```ts title="manage/roles/delete.ts"
        import { ApplicationCommandOptionType, codeBlock } from "discord.js";
        import group from "./group.js";

        group.subcommand({
            name: "delete",
            description: "Delete a role",
            options: [
                {
                    name: "role",
                    description: "Select the role",
                    type: ApplicationCommandOptionType.Role,
                    required: true,
                },
            ],
            async run(interaction) {
                const { options } = interaction;

                const role = options.getRole("role", true);

                await interaction.reply({
                    flags: ["Ephemeral"],
                    content: "Deleting role..."
                });

                await role.delete()
                    .then(() => interaction.editReply({
                        content: "Channel deleted!"
                    }))
                    .catch(err => interaction.editReply({
                        content: `Error: ${codeBlock(err)}`
                    }));
            },
        })
        ```
      </Tab>

      <Tab value="permissions">
        ```ts title="manage/roles/permissions.ts"
        import { ApplicationCommandOptionType, codeBlock, PermissionFlagsBits, PermissionsString } from "discord.js";
        import group from "./group.js";

        group.subcommand({
            name: "permissions",
            description: "Change role permissions",
            options: [
                {
                    name: "role",
                    description: "Select the role",
                    type: ApplicationCommandOptionType.Role,
                    required: true,
                },
                {
                    name: "action",
                    description: "Select the action",
                    type: ApplicationCommandOptionType.String,
                    choices: [
                        { name: "Add", value: "add" },
                        { name: "Remove", value: "remove" },
                    ],
                    required: true,
                },
                {
                    name: "permission",
                    description: "Select the permission",
                    type: ApplicationCommandOptionType.String,
                    choices: Object.keys(PermissionFlagsBits)
                        .map(value => ({ name: value, value })),
                    required: true,
                },
            ],
            async run(interaction) {
                const { options } = interaction;

                const role = options.getRole("role", true);
                const action = options.getString("action", true) as "add" | "remove";
                const permission = options.getString("permission") as PermissionsString;

                await interaction.reply({
                    flags: ["Ephemeral"],
                    content: "Update permissions..."
                });

                const permissions = role.permissions[action](permission).toArray();

                role.edit({ permissions })
                    .then(role => interaction.editReply({
                        content: `${action} permissions: ${role}`
                    }))
                    .catch(err => interaction.editReply({
                        content: `Error: ${codeBlock(err)}`
                    }));
            },
        })
        ```
      </Tab>
    </Tabs>
  </Tab>
</Tabs>

# Transporte de dados [#transporte-de-dados]

Você pode transportar dados entre os grupos e sub comandos simplesmente retornando eles nas funções <CodeSpan.Method identifier="run" /> de cada um. Vamos ver um exemplo simples:

```ts title="store/command.ts"
import { createCommand } from "#base";
import { db } from "#database";

export default createCommand({
    name: "store",
    async run(interaction) {
        const { guild } = interaction;

        await interaction.deferReply({ flags: ["Ephemeral"] });

        const storeData = await db.store.findOne({ // [!code highlight]
            guildId: guild.id // [!code highlight]
        }); // [!code highlight]

        return storeData // StoreDocument
    },
});
```

Acima temos algo como uma consulta ao banco de dados para obter o documento do nosso sistema de loja. Quando retornamos algo dentro do <CodeSpan.Method identifier="run" />, ele será passado como o segundo argumento para o <CodeSpan.Method identifier="run" /> dos grupos e sub comandos, tudo isso com tipagem inferida automaticamente!

<CodeBlockTabs defaultValue="setup">
  <CodeBlockTabsList>
    <CodeBlockTabsTrigger value="setup">
      setup
    </CodeBlockTabsTrigger>

    <CodeBlockTabsTrigger value="close">
      close
    </CodeBlockTabsTrigger>
  </CodeBlockTabsList>

  <CodeBlockTab value="setup">
    ```ts  title="store/setup.ts"
    import command from "./command.js";
    import { codeBlock } from "discord.js";

    // [!code word:data]
    command.subcommand({
        name: "setup",
        async run(interaction, data /* StoreDocument */) {
            const { channelId, description } = data; // [!code highlight]
            
            const channel = await interaction.guild.channels
                .fetch(channelId)
                .catch(() => null);

            if (!channel || !channel.isSendable()) {
                await interaction.editReply("Store channel not found");
                return;
            }

            const message = await channel.send({ content: description })
                .catch(err => {
                    interaction.editReply({
                        content: `Unable to setup store: ${codeBlock(err)}`
                    });
                    return null;
                });

            if (!message) return;

            data.set("panelMessageURL", message.url);
            await data.save();
        },
    });
    ```
  </CodeBlockTab>

  <CodeBlockTab value="close">
    ```ts  title="store/close.ts"
    import { getMessageURLInfo } from "@magicyan/discord";
    import command from "./command.js";
    // [!code word:data]

    command.subcommand({
        name: "close",
        async run(interaction, data /* StoreDocument */) {
            const { panelMessageURL } = data; // [!code highlight]

            const messageInfo = getMessageURLInfo(panelMessageURL);

            if (!messageInfo.messageId) {
                await interaction.editReply("Message not found");
                return;
            }

            const message = await interaction.guild.channels
                .fetch(messageInfo.channelId)
                .then(channel => channel?.isSendable()
                    ? channel.messages.fetch(messageInfo.messageId)
                    : null
                )
                .catch(() => null);

            if (!message) {
                await interaction.editReply("Store panel message not found!");
                return;
            }

            await message.delete();

            await interaction.editReply("Store panel message deleted!");

            data.set("isOpen", false);
            data.delete("panelMessageURL", null);
            await data.save();
        },
    });
    ```
  </CodeBlockTab>
</CodeBlockTabs>

Se você tiver grupos é possível transformar ou enviar novos dados para os sub comandos

<Steps>
  <Step>
    ```ts title="command.ts"
    export default createCommand({
        /* ... */
        async run(){
            // ...
            return "Constatic";  // [!code highlight]
        }
    })
    ```
  </Step>

  <Step>
    ```ts title="group.ts"
    import command from "./command.js";

    export default command.group({
        /* ... */
        async run(_, text /* string */){ // [!code highlight]
            // ...

            console.log(text) 
            // "Constatic"

            return text.split("");
        }
    })
    ```
  </Step>

  <Step>
    ```ts title="subcommand.ts"
    import group from "./command.js";

    group.subcommand({
        /* ... */
        async run(_, words /* string[] */){ // [!code highlight]
            // ...
            console.log(worlds) 
            // ['C', 'o', 'n', 's', 't', 'a', 't', 'i', 'c']
        }
    })
    ```
  </Step>
</Steps>
# Menu de contexto (/pt/docs/discord/commands/context)



## Criando menus de contexto [#criando-menus-de-contexto]

<Callout type="success">
  É possível definir algumas opções para os comandos na função <CodeSpan.Method identifier="setupCreators" />!

  [Veja mais detalhes na página sobre as funções criadoras](/docs/discord/creators#command-options)
</Callout>

Menus de contexto não tem descrição e o nome desses comandos pode conter letras maíusculas e espaços.

<Tabs items="[&#x22;Menu de contexto de usuário&#x22;, &#x22;Menu de contexto de mensagem&#x22;]">
  <Tab value="Menu de contexto de usuário">
    Para criar um comando de menu de contexto de usuário, você precisa definir <CodeSpan.Prop identifier="name" /> e <CodeSpan.Prop identifier="type" />.

    ```ts
    createCommand({
        name: "Perfil",
        type: ApplicationCommandType.User,
        async run(interaction) {
            const { targetUser } = interaction;
            
            await interaction.reply({ 
              flags: ["Ephemeral"], 
              content: `${targetUser}"s profile` 
            });
        },
    });
    ```
  </Tab>

  <Tab value="Menu de contexto de mensagem">
    Para criar um comando de menu de contexto de mensagem, você precisa definir <CodeSpan.Prop identifier="name" /> e <CodeSpan.Prop identifier="type" />.

    ```ts
    createCommand({
        name: "Dar olá",
        type: ApplicationCommandType.Message,
        async run(interaction) {
            const { targetMessage } = interaction;
            
            await interaction.deferReply({ 
              flags: ["Ephemeral"], 
            });
            await targetMessage.reply("Olá!");
        },
    });
    ```
  </Tab>
</Tabs>
# Autocomplete (/pt/docs/discord/commands/autocomplete)



# O que é autocomplete? [#o-que-é-autocomplete]

Imagine que você queira fornecer escolhas para uma opção de um comando mas de forma dinâmica, por exemplo um comando para pesquisar vídeos no youtube. Você pode usar a opção <CodeSpan.Method identifier="autocomplete" />, assim com base no que o usuário digitar nessa opção, você pode fazer buscas em APIs e retornar uma lista de escolhas.

# Criando uma opção autocomplete [#criando-uma-opção-autocomplete]

<Callout type="warn">
  É preciso ter um [comando de barra](/docs/discord/commands/slash) para criar uma opção autocomplete
</Callout>

Apenas opções do tipo **String**, **Number** e **Integer** podem ser autocomplete. Para isso basta definir a propriedade <CodeSpan.Method identifier="autocomplete" /> como verdadeira no objeto da opção no seu comando:

```ts title="command.ts"
createCommand({
  	name: "busca",
	description: "Comando de busca",
	type: ApplicationCommandType.ChatInput,
	options: [
		{
			name: "termo",
			description: "termo",
			type: ApplicationCommandOptionType.String,
			autocomplete: true, // [!code ++]
			required,
		}
	],
	// ...
});
```

# Respondendo a opção autocomplete [#respondendo-a-opção-autocomplete]

Quando o usuário digitar algo na opção do comando lá no discord, o evento **interactionCreate** é emitido com uma interação autocomplete. Você pode responder ela no comando dessa forma:

```ts title="command.ts"
createCommand({
  	name: "busca",
	description: "Comando de busca",
	type: ApplicationCommandType.ChatInput,
	options: [
		{
			name: "termo",
			description: "termo",
			type: ApplicationCommandOptionType.String,
			autocomplete: true,
			required,
		}
	],
	// [!code word:autocomplete]
	async autocomplete(interaction) { // [!code ++]
		const focused = interaction.options.getFocused(); // [!code ++]
		const results = await searchData(focused); // [!code ++]
		if (results.length < 1) return; // [!code ++]
		const choices = results.map(data => ({ // [!code ++]
			name: data.title, value: data.url // [!code ++]
		})); // [!code ++]
		return choices; // [!code ++]
	},
	// ...
});
```

Essa função irá retornar uma **lista de escolhas** que o usuário poderá escolher na opção! Para obter a opção escolhida quando o comando for enviado, pegue a opção pelo nome dela:

```ts title="command.ts"
createCommand({
  	name: "busca",
	description: "Comando de busca",
	type: ApplicationCommandType.ChatInput,
	options: [
		{
			name: "termo",
			autocomplete: true,
			// **
		}
	],
	async autocomplete(interaction) {
		// **
	},
	async run(interaction){ 
		const { options } = interaction;

		const query = options.getString("termo", true); // [!code ++]
		
		interaction.reply({ flags: ["Ephemeral"], content: query });
	}
});
```

<Callout type="info">
  Note que você pode apenas retornar as opções, pois o manipulador de comandos autocomplete irá automaticamente limitar os itens do array em `25`

  ```ts
  // ...
  return choices; // [!code highlight]
  // ...
  ```
</Callout>

Se você tiver uma grande quantidade de itens, use o autocomplete para tentar encontrá-los

```ts title="command.ts"
createCommand({
    // ...
    async autocomplete(interaction) {
		const { options, guild } = interaction;

        const focused = options.getFocused();
        const documents = await db.get(guild.id);

        const filtered = documents.filter(
            data => data.address.toLowercase().includes(focused.toLowercase())
        )
        if (filtered.length < 1) return;
        return filtered.map(data => ({
			name: data.title, value: data.url
		}));
	},
    // ...
})
```

<Callout type="info">
  Se você preferir, pode usar o método <CodeSpan.Method identifier="respond" /> da interação como faria normalmente:

  ```ts
  return choices; // [!code --]
  interaction.respond(choices.slice(0, 25)) // [!code ++]
  ```
</Callout>

# Múltiplas opções autocomplete [#múltiplas-opções-autocomplete]

Se você tiver muitas opções autocomplete no seu comando, será necessário verificar qual é a opção para poder responder ela corretamente. Considere essas opções:

```ts title="command.ts"
import { createCommand } from "#base";
import { includesIgnoreCase } from "@magicyan/discord";
import { ApplicationCommandOptionType, ApplicationCommandType } from "discord.js";
import { fetchWithCache } from "#functions";
import { env } from "#env";

createCommand({
    name: "search",
    description: "app command",
    type: ApplicationCommandType.ChatInput,
    options: [
        {
            name: "application",
            description: "your custom application",
            type: ApplicationCommandOptionType.String,
            required: true,
            autocomplete: true,
        },
        {
            name: "video",
            description: "video name, description or tags",
            type: ApplicationCommandOptionType.String,
            required: true,
            autocomplete: true,
        },
        {
            name: "subscriptor",
            description: "select the subscriptor",
            type: ApplicationCommandOptionType.String,
            required: true,
            autocomplete: true,
        },
    ],
    // ...
});
```

Cada uma delas recebe escolhas diferentes, então você teria que fazer algo como isso:

```ts title="command.ts"
createCommand({
    name: "search",
    description: "app command",
    type: ApplicationCommandType.ChatInput,
    options: [
        // ...
    ],
    async autocomplete({ options }) {
        const { name, value } = options.getFocused(true);

        switch (name) {
            case "application": {
                const apps = await fetchWithCache({
					url: `${env.API_URL}/apps`
					seconds: 30
				});

                return apps
                    .filter(app => includesIgnoreCase(app.name, value))
                    .map(app => ({
                        name: app.name,
                        value: app.id
                    }));
            }
            case "video": {
                const appId = options.getString("application", true);
                const app = await fetchWithCache({ 
					url: `${env.API_URL}/apps/${appId}`,
					seconds: 50 
				});

                return app.videos
                    .filter(video =>
                        includesIgnoreCase(video.title, value) ||
                        includesIgnoreCase(video.description, value) ||
                        video.tags.includes(value)
                    )
                    .map(video => ({
                        name: video.title,
                        value: video.id
                    }));
            }
            default: {
                const videoId = options.getString("video", true);
                const video = await fetchWithCache({ 
					url: `${env.API_URL}/videos/${videoId}`,
					seconds: 50
				});

                return video.subscriptors
                    .filter(sub => includesIgnoreCase(sub.name, value))
                    .map(sub => ({
                        name: sub.title,
                        value: sub.id
                    }));
            }
        }
    }
});
```

Você pode preferir utilizar um recurso exclusivo dessa base para responder as interações autocomplete diretamente no objeto da opção.

Ao invés de definir um boleano verdadeiro, você pode definir diretamente a função que responde aquela opção, assim não é necessário verificar qual é a opção autocomplete, pois o manipulador já fará isso pra você:

```ts title="command.ts"
import { createCommand } from "#base";
import { includesIgnoreCase } from "@magicyan/discord";
import { ApplicationCommandOptionType, ApplicationCommandType } from "discord.js";
import { fetchWithCache } from "#functions";
import { env } from "#env";

createCommand({
    name: "search",
    description: "app command",
    type: ApplicationCommandType.ChatInput,
    options: [
        {
            name: "application",
            description: "your custom application",
            type: ApplicationCommandOptionType.String,
            required: true,
            async autocomplete({ options }){ // [!code ++]
                const apps = await fetchWithCache({  // [!code ++]
					url: `${env.API_URL}/apps`, // [!code ++]
					seconds: 30  // [!code ++]
				}); // [!code ++]
                return apps // [!code ++]
                    .filter(app => includesIgnoreCase(app.name, options.getFocused())) // [!code ++]
                    .map(app => ({ // [!code ++]
                        name: app.name, // [!code ++]
                        value: app.id // [!code ++]
                    })); // [!code ++]
			}  // [!code ++]
        },
        {
            name: "video",
            description: "video name, description or tags",
            type: ApplicationCommandOptionType.String,
            required: true,
            async autocomplete(){  // [!code ++]
                const appId = options.getString("application", true);   // [!code ++]
                const app = await fetchWithCache({  // [!code ++]
					url: `${env.API_URL}/apps/${appId}`  // [!code ++]
					seconds: 50   // [!code ++]
				});  // [!code ++]
				const query = options.getFocused();  // [!code ++]
                return app.videos  // [!code ++]
                    .filter(video =>  // [!code ++]
                        includesIgnoreCase(video.title, query) ||  // [!code ++]
                        includesIgnoreCase(video.description, query) ||  // [!code ++]
                        video.tags.includes(query)  // [!code ++]
                    )  // [!code ++]
                    .map(video => ({  // [!code ++]
                        name: video.title,  // [!code ++]
                        value: video.id  // [!code ++]
                    })); // [!code ++]		
			}  // [!code ++]
        },
        {
            name: "subscriptor",
            description: "select the subscriptor",
            type: ApplicationCommandOptionType.String,
            required: true,
            async autocomplete(){  // [!code ++]
                const videoId = options.getString("video", true);  // [!code ++]
                const video = await fetchWithCache({ // [!code ++]
					url: `${env.API_URL}/videos/${videoId}` // [!code ++]
					seconds: 50 // [!code ++]
				});  // [!code ++]
                return video.subscriptors  // [!code ++]
                    .filter(sub => includesIgnoreCase(sub.name, options.getFocused()))  // [!code ++]
                    .map(sub => ({  // [!code ++]
                        name: sub.title,  // [!code ++]
                        value: sub.id  // [!code ++]
                    }));  // [!code ++]				
			}  // [!code ++]
        },
    ],
	async autocomplete({ options }){ // [!code --]
    // ... // [!code --]
	} // [!code --]
});
```
# Botões (/pt/docs/discord/responders/buttons)



Responda um botão definindo o tipo do <CodeSpan.Class identifier="Responder" /> para botão.

```ts title="command.ts"
import { createRow, createComponents } from "@magicyan/discord";

const row = createRow(
    new ButtonBuilder({
        customId: "/system/confirm", 
        label: "Confirm", 
        style: ButtonStyle.Success
    })
);
await interaction.reply({ 
    flags: ["Ephemeral", "IsComponentsV2"], 
    components: createComponents(row) 
});
```

```ts title="responder.ts"
createResponder({
    customId: "/system/confirm",
    // [!code word:Button]
    types: [ResponderType.Button], cache: "cached",
    async run(interaction) {
        interaction.update({ 
            components: createComponents(
                "Confirmado"
            )
        });
    },
});
```
# Menus de seleção (/pt/docs/discord/responders/selects)



## Criando Responder para menu de seleção [#criando-responder-para-menu-de-seleção]

É possível criar um <CodeSpan.Class identifier="Responder" /> que pode aceitar vários tipos de menus de seleção, veja um exemplo:

```ts title="command.ts"
// ...
import { createComponents } from "@magicyan/discord";

await interaction.reply({ 
    flags: ["Ephemeral", "IsComponentsV2"], 
    components: createComponents(
        new StringSelectMenuBuilder({
            customId: "/fruits",
            placeholder: "Selecione frutas",
            options: [
                { emoji: "🍎", label: "Maçã", value: "apple" },
                { emoji: "🍉", label: "Melancia", value: "melon" },
                { emoji: "🍊", label: "Laranja", value: "orange" }
            ]
        })
    ) 
});
// ...
```

Acima está o código para enviar um menu de seleção comum como resposta do comando. Logo abaixo você pode ver um <CodeSpan.Class identifier="Responder" /> com <CodeSpan.Enum identifier="ResponderType" member="StringSelect" /> nos tipos, assim a função <CodeSpan.Method identifier="run" /> deste Responder será executada quando alguém selecionar neste menu de seleção:

```ts title="responder.ts"
createResponder({
    customId: "/fruits",
    // [!code word:StringSelect]
    types: [ResponderType.StringSelect], cache: "cached",
    async run(interaction) {
        const selected = interaction.values[0];
        interaction.update({ 
            components: createComponents(
                `${selected} Selecionada`
            ), 
        });
    },
});
```

Você pode combinar diversos tipos de menus de seleção diferentes:

```ts title="responder.ts"
createResponder({
    customId: "/ban/user", cache: "cached",
    types: [
        ResponderType.StringSelect,
        ResponderType.UserSelect,
    ],
    async run(interaction) {
        const { guild, values: [selected] } = interaction;

        await interaction.update({});

        if (interaction.isUserSelectMenu()){
            const member = guild.members.get(selected);
            await member.ban(); 
        } else {
            const member = guild.members.cache
                .find(m => m.user.username === selected);
            await member.ban(); 
        }

        await interaction.editReply({ 
            components: createComponents(
                `${userMention(selected)} foi banido!`
            )
        });
    },
});
```

Abaixo estão todos os tipos de menus de seleção:

| Menu de seleção | ResponderType                                                           |
| --------------- | ----------------------------------------------------------------------- |
| Strings         | <CodeSpan.Enum identifier="ResponderType" member="StringSelect" />      |
| Usuários        | <CodeSpan.Enum identifier="ResponderType" member="UserSelect" />        |
| Canais          | <CodeSpan.Enum identifier="ResponderType" member="ChannelSelect" />     |
| Cargos          | <CodeSpan.Enum identifier="ResponderType" member="RoleSelect" />        |
| Menções         | <CodeSpan.Enum identifier="ResponderType" member="MentionableSelect" /> |

É possível combinar com qualquer tipo, dessa forma você pode ter um botão, um menu de seleção e um modal com o mesmo customId e todos serão respondidos nesta função, basta fazer verificações:

```ts title="responder.ts"
createResponder({
    customId: "/menus/main", cache: "cached",
    types: [
        ResponderType.Button,
        ResponderType.StringSelect,
        ResponderType.ModalComponent,
    ],
    async run(interaction) {
        switch (true) {
            case interaction.isButton():
                console.log("Botão")
                return;
            case interaction.isStringSelect():
                console.log("Menu de seleção", interaction.values);
                return;
            default:
                console.log("Modal", interaction.fields);
                return;
        }
    },
});
```
# Modais (/pt/docs/discord/responders/modals)



## Criando Responder para modais [#criando-responder-para-modais]

Abaixo você pode ver um trecho de código respondendo a interação de um comando exibindo um modal:

```ts title="command.ts"
import { createModalFields } from "@magicyan/discord";

// ...
interaction.showModal({
    customId: "/register/form",
    title: "Formulário",
    components: createModalFields(
        createLabel(
            "Qual é o seu nome?",
            createTextInput({ customId: "name" })
        ),
        createLabel(
            "Qual é a sua idade?",
            createTextInput({ customId: "age" })
        ),
    )
});
// ...
```

Para responder um modal com o <CodeSpan.Class identifier="Responder" />, adicione nos tipos o <CodeSpan.Enum identifier="ResponderType" member="Modal" />:

```ts title="responder.ts"
createResponder({
    customId: "/register/form",
    // [!code word:Modal]
    types: [ResponderType.Modal], cache: "cached",
    async run(interaction) {
        const { fields, member } = interaction;
        const name = fields.getTextInputValue("name");
        const age = fields.getTextInputValue("age");

        await registerMember(member, { name, age }); // Função de exemplo

        interaction.reply({ flags: ["Ephemeral"], content: `Registrado como ${name}` });
    },
});
```

Se o modal for exibido a partir de um componente:

```ts title="responder.ts"
createResponder({
    customId: "/open/form",
    // [!code word:Modal]
    types: [ResponderType.Button], cache: "cached",
    async run(interaction) {
        await interaction.showModal({
            customId: "/register/form",
            title: "Formulário",
            components: createModalFields(
                createLabel(
                    "Qual é o seu nome?",
                    createTextInput({ customId: "name" })
                ),
                createLabel(
                    "Qual é a sua idade?",
                    createTextInput({ customId: "age" })
                ),
            )
        });
    },
});
```

Você pode usar o tipo <CodeSpan.Enum identifier="ResponderType" member="ModalComponent" />:

```ts title="responder.ts"
createResponder({
    customId: "/register/form",
    // [!code word:ModalComponent]
    types: [ResponderType.ModalComponent], cache: "cached",
    async run(interaction) {
        // ...
    },
});
```

<Callout type="info">
  Se você criar um código que possa exibir o mesmo modal tanto a partir de um comando quanto a partir de um componente, basta incluir os dois tipos no array de tipos do Responder:

  <CodeBlockTabs defaultValue="Comando">
    <CodeBlockTabsList>
      <CodeBlockTabsTrigger value="Comando">
        Comando
      </CodeBlockTabsTrigger>

      <CodeBlockTabsTrigger value="Componente">
        Componente
      </CodeBlockTabsTrigger>
    </CodeBlockTabsList>

    <CodeBlockTab value="Comando">
      ```ts
      import { myCustomModals } from "#modals" // Exemplo

      createCommand({
          name: "formulário",
          async run(interaction) {
              await interaction.showModal(
                  myCustomModals.formModal()
              );
          },
      });
      ```
    </CodeBlockTab>

    <CodeBlockTab value="Componente">
      ```ts
      import { myCustomModals } from "#modals" // Exemplo

      createResponder({
          customId: "/open/form",
          types: [ResponderType.Button], cache: "cached",
          async run(interaction) {
              await interaction.showModal(
                  myCustomModals.formModal()
              );
          },
      });
      ```
    </CodeBlockTab>
  </CodeBlockTabs>

  ```ts title="responder.ts"
  createResponder({
      customId: "/register/form",
      types: [
      // [!code word:Modal:1]
          ResponderType.Modal,
      // [!code word:ModalComponent]
          ResponderType.ModalComponent
      ], cache: "cached",
      async run(interaction) {
          // ...
      },
  });
  ```
</Callout>
# Parâmetros (/pt/docs/discord/responders/params)





## O que são CustomID params? [#o-que-são-customid-params]

Vamos um pouco além do convencional, nesta base um recurso presente em diversas ferramentas de servidor API foi implementado para permitir que sistemas mais avançados possam ser desenvolvidos com mais praticidade.

Igual em rotas HTTP, podemos passar parâmetros para os `customIds` de botões, menus de seleção e modais. Veja como é simples:

Primeiro vamos criar um comando de contexto de usuário:

```ts title="src/discord/commands/context/manage.ts"
import { createContainer, createRow } from "@magicyan/discord";

createCommand({
    name: "Gerenciar",
    type: ApplicationCommandType.User,
    async run(interaction){
        const { targetUser } = interaction;

        createContainer("#5147da",
            `Gerenciar ${targetUser}`,
            createRow(
                new ButtonBuilder({ 
                    customId: `/manage/user/${targetUser.id}/kick`, 
                    label: "Expulsar", style: ButtonStyle.Secondary 
                }),
                new ButtonBuilder({ 
                    customId: `/manage/user/${targetUser.id}/ban`, 
                    label: "Banir", style: ButtonStyle.Danger 
                }),
                new ButtonBuilder({ 
                    customId: `/manage/user/${targetUser.id}/timeout`, 
                    label: "Castigo", style: ButtonStyle.Danger 
                }),
                new ButtonBuilder({ 
                    customId: `/manage/user/${targetUser.id}/alert`, 
                    label: "Alertar", style: ButtonStyle.Primary 
                })
            )
        );

        await interaction.reply({ 
            flags: ["Ephemeral", "IsComponentsV2"], 
            components: [container] 
        });
    }
});
```

<Accordions>
  <Accordion title="Repare que o customId de todos os botões tem uma semelhança, ambos seguem um padrão, onde cada segmento é separado por / (barra)">
    ```ts
    // ...
    // [!code word:/]
    new ButtonBuilder({ 
        customId: `/manage/user/${targetUser.id}/kick`,  // [!code highlight]
        label: "Expulsar", style: ButtonStyle.Secondary 
    }),
    new ButtonBuilder({ 
        customId: `/manage/user/${targetUser.id}/ban`, // [!code highlight]
        label: "Banir", style: ButtonStyle.Danger 
    }),
    new ButtonBuilder({ 
        customId: `/manage/user/${targetUser.id}/timeout`, // [!code highlight]
        label: "Castigo", style: ButtonStyle.Danger 
    }),
    new ButtonBuilder({ 
        customId: `/manage/user/${targetUser.id}/alert`, // [!code highlight]
        label: "Alertar", style: ButtonStyle.Primary 
    })
    // ...
    ```
  </Accordion>
</Accordions>

Com isso podemos criar um <CodeSpan.Class identifier="Responder" /> que espera qualquer componente de botão que siga esse padrão no customId.

Ele deve começar com `/manage/user` logo depois deve ter mais dois segmentos de parâmetros separados por `/` e começando com `:`, onde o primeiro será o id do usuário e o segundo vai ser uma ação.

<Callout type="info">
  Ficaria dessa maneira: `/manage/user/:userId/:action`
</Callout>

Então podemos definir esse padrão e qualquer botão onde o customId seguir ele, será respondido pela função definida. Você pode obter os parâmetros no segundo argumento da função.

```ts title="src/discord/responders/manage.ts"
// Dynamic button component function
createResponder({
    customId: "/manage/user/:userId/:action",
    types: [ComponentType.Button], cache: "cached",
    async run(interaction, params) {
        const { action, userId } = params;
        const targetMember = await interaction.guild.members.fetch(userId);

        switch(action){
            case "kick": {
                targetMember.kick();
                // fazer coisas ...
                break;
            }
            case "ban": {
                targetMember.ban();
                // fazer coisas ...
                break;
            }
            case "timeout": {
                targetMember.timeout(60000);
                // fazer coisas ...
                break;
            }
            case "alert": {
                targetMember.send({ /* ... */ });
                // fazer coisas ...
                break;
            }
        }
    },
});
```

<Callout type="danger">
  Você pode usar esse recurso com qualquer tipo de <CodeSpan.Class identifier="Responder" />, mas não esqueça que o discord tem um limite de 100 caracteres nos customIds.
</Callout>

## Transformando parâmetros de CustomID [#transformando-parâmetros-de-customid]

A função <CodeSpan.Method identifier="createResponder" /> tem uma opção onde você pode especificar uma forma de transformar o objeto de parâmetros que inicalmente tanto as chaves, quantos os valores são somente strings. Confira:

<Tabs items="[&#x22;Transformação simples&#x22;, &#x22;Transformando datas&#x22;, &#x22;Transformação opcional&#x22;, &#x22;Esquema Zod&#x22;]">
  <Tab value="Transformação simples">
    Transforme o parâmetro `value` em um número, assim podendo usar funções numéricas

    ```ts title="Botão"
    new Button({
        customId: "/count/1",
        label: "Contagem", 
        style: ButtonStyle.Primary 
    })
    ```

    ```ts title="Responder"
    createResponder({
        customId: "/count/:value", cache: "cached",
        types: [ComponentType.Button],
        parse: params => ({ // [!code highlight]
            value: Number.parseInt(params.value) // [!code highlight]
        }), // [!code highlight]
        async run(interaction, { value }) {
            console.log(value + 1); // 2
            console.log(value.toFixed(2)); // "1.00"
        }
    });
    ```
  </Tab>

  <Tab value="Transformando datas">
    Você pode passar datas ISO string também:

    ```ts title="Botão"
    new Button({
        customId:`/remind/${new Date().toISOString()}`
        // customId: `/remind/2018-11-30T12:20:00.000Z`,
        label: "Lembrar", 
        style: ButtonStyle.Success 
    });
    ```

    ```ts title="Responder"
    createResponder({
        customId: "/remind/:date", cache: "cached",
        types: [ComponentType.Button],
        parse: params => ({ // [!code highlight]
            date: new Date(params.date) // [!code highlight]
        }), // [!code highlight]
        async run(interaction, { date }) {
            console.log(date.getHours()) // 9
            console.log(date.getMinutes()) // 20
            console.log(date.getDate()); // 30
            console.log(date.getMonth()); // 10
            console.log(date.getFullYear()); // 2018
        }
    });
    ```
  </Tab>

  <Tab value="Transformação opcional">
    Você não precisa espeficicar todas as propriedades dos parâmetros, vamos supor que você só queira transformar uma propriedade e manter todo o resto como string:

    ```ts title="Botão"
    new Button({
        customId:`/embeds/1/title/create`
        label: "Criar", 
        style: ButtonStyle.Success 
    });
    ```

    ```ts title="Responder"
    createResponder({
        customId: "/embeds/:index/:menu/:action", cache: "cached",
        types: [ComponentType.Button],
        parse: params => ({ // [!code highlight]
            ...params, // [!code highlight]
            index: Number.parseInt(params.index) // [!code highlight]
        }), // [!code highlight]
        async run(interaction, { index, menu, action }) {
            const embed = embeds[index];

            switch(menu){
                // ...
            }
        }
    });
    ```
  </Tab>

  <Tab value="Esquema Zod">
    Para customIds maiores você pode utilizar um esquema da lib zod, que já vem nas dependencias da base:

    ```ts title="Botão"
    new Button({
        customId:`/menus/${user.id}/channels/create`
        label: "Criar novo canal", 
        style: ButtonStyle.Success 
    });
    ```

    ```ts title="Responder"
    import { z } from "zod"; // [!code highlight]

    createResponder({
        customId: "/menus/:userId/:menu/:action",
        types: [ResponderType.Button], cache: "cached",
        parse: z.object({ // [!code highlight]
            userId: z.string(), // [!code highlight]
            menu: z.enum(["channels", "roles", "parents"]), // [!code highlight]
            action: z.enum(["create", "updated", "delete"]) // [!code highlight]
        }).parse, // [!code highlight]
        async run(interaction, { menu, action, userId }) {
            menu // "channels" | "roles" | "parents"
            action // "create" | "updated" | "delete"
        },
    })
    ```
  </Tab>
</Tabs>

## Wildcards [#wildcards]

Você pode usar wildcards também se quiser responder a rotas com mais ou menos segmentos

<Tabs items="[&#x22;Usando wildcard&#x22;, &#x22;Wildcard nomeado&#x22;, &#x22;Transformando wildcard&#x22;]">
  <Tab value="Usando wildcard">
    Use `**` para representar qualquer padrão de segmentos após a `/` (barra)

    ```md title="CustomIds que serão respondidos"
    - "/giveway"
    - "/giveway/users"
    - "/giveway/gifts/nitro"
    - "/giveway/gifts/account/creator/expiresAt"
    ```

    ```ts title="Responder"
    createResponder({
        customId: "/giveway/**", cache: "cached",
        types: [ComponentType.Button],
        async run(interaction, { _ }) {
            // /giveway _: ""
            // /giveway/users _: "users"
            // /giveway/gifts/nitro _:"gifts/nitro"
            // /giveway/gifts/account/creator/expiresAt _:"gifts/account/creator/expiresAt"
        }
    });
    ```
  </Tab>

  <Tab value="Wildcard nomeado">
    De um nome para o wildcard ao invés de `_`, use `:` para definir um nome:

    ```md title="CustomIds que serão respondidos"
    - "/giveway/users"
    - "/giveway/gifts/nitro"
    - "/giveway/gifts/account/creator/expiresAt"
    ```

    ```ts title="Responder"
    createResponder({
        customId: "/giveway/**:args", cache: "cached",
        types: [ComponentType.Button],
        async run(interaction, { args }) {
            // /giveway/users args: "users"
            // /giveway/gifts/nitro args:"gifts/nitro"
            // /giveway/gifts/account/creator/expiresAt args:"gifts/account/creator/expiresAt"
        }
    });
    ```

    <Callout type="warn">
      Definindo um nome para o wildcard, agora se torna obrigatório o customId ter mais um segmento, ou seja, ele não responderá a apenas `giveway`, somente `giveway/args...`.
    </Callout>
  </Tab>

  <Tab value="Transformando wildcard">
    Você pode usar o método `parse` para transformar o wildcard no que quiser, por exemplo um array

    ```md title="CustomIds que serão respondidos"
    - "/giveway"
    - "/giveway/users"
    - "/giveway/gifts/nitro"
    - "/giveway/gifts/account/creator/expiresAt"
    ```

    ```ts title="Responder"
    createResponder({
        customId: "/giveway/**", cache: "cached",
        types: [ComponentType.Button],
        parse: params => ({
            args: params._.split("/").filter(Boolean)
        }),
        async run(interaction, { args }) {
            // /giveway args: []
            // /giveway/users args: ["users"]
            // /giveway/gifts/nitro args: ["gifts", "nitro"]
            // /giveway/gifts/account/creator/expiresAt args: ["gifts", "account", "creator", "expiresAt"]
        }
    });
    ```
  </Tab>
</Tabs>

<Callout type="info">
  Os exemplos dessa página foram todos com botões, mas este recurso pode ser utilizado com qualquer tipo de responder!
</Callout>
# Emitir (/pt/docs/discord/responders/emit)



O manipulador de Responder que você cria será executado quando um evento de interação for emitido! Mas você pode emitir seu próprio evento de interação de forma simples usando a função <CodeSpan.Method identifier="emitResponder" />:

```ts
import { emitResponder } from "@constatic/base";

emitResponder("/foo/bar", interaction);
```

Passe o customId do Responder correspondente no primeiro argumento e uma interação de qualquer tipo no segundo argumento.

Então o manipulador <CodeSpan.Method identifier="run" /> do **Responder** será executado:

```ts
import { createResponder } from "#base";
import { ResponderType } from "@constatic/base";

createResponder({
    customId: "/foo/bar",
    types: [ResponderType.Button], cache: "cached",
    async run(interaction){
        // fazer coisas
    }
});
```

Você pode passar [parâmetros de customId](/docs/discord/responders/params) na função <CodeSpan.Method identifier="emitResponder" /> e eles chegarão no **Responder**:

```ts

emitResponder(`/remember/${Date.now()}`, interaction)
//                        ^ "1780301472577"

// ...
createResponder({
    customId: "/remember/:date",
    types: [ResponderType.Button], cache: "cached",
    async run(interaction, { date }){ // "1780301472577"
        console.log(new Date(date)) // Date Mon Jun 01 2026
    }
});
```

<Callout type="danger">
  Mas tome cuidado para não criar um loop infinito:

  ```ts
  createResponder({
      customId: "/foo/bar",
      types: [ResponderType.Button], cache: "cached",
      async run(interaction){
          emitResponder("/foo/bar", interaction);
      }
  });
  ```
</Callout>
# Eventos (/pt/docs/discord/events)



## Criando funções para ouvintes de eventos [#criando-funções-para-ouvintes-de-eventos]

<Callout type="success">
  É possível definir algumas opções para os eventos na função <CodeSpan.Method identifier="setupCreators" />!

  [Veja mais detalhes na página sobre as funções criadoras](/docs/discord/creators#event-options)
</Callout>

Para criar uma função para um ouvinte de evento do discord, use a função <CodeSpan.Method identifier="createEvent" />

Primeiro faça a importação da base

```ts title="src/events/myevent.ts"
import { createEvent } from "#base";
```

Use a propriedade <CodeSpan.Prop identifier="name" /> para criar um identificador personalizado para o seu evento, depois defina qual evento do discord você espera usando a propriedade `event`.

```ts
import { createEvent } from "#base";

createEvent({
    name: "Message edit logs",
    event: "messageUpdate",
    async run(oldMessage, newMessage) {
        console.log("Message edited at:", newMessage.editedAt?.toDateString());
        console.log("Author", newMessage.author?.displayName);
        console.log("Old message content: ", oldMessage.content);
        console.log("New message content:", newMessage.content);   
    }
});
```

Todos os eventos do discord são tipados pela propriedade `event`, quando escolher um evento, o método run será tipado automaticamente com todos os argumentos que esse evento recebe.

<Callout type="warn">
  Se você criar funções para o evento `ready` do discord, elas só serão executadas após o evento ready principal do bot, incluíndo as execuções do evento principal.

  O evento `ready` é definido como `once` automaticamente, dessa maneira a função é deletada após ser executada, assim garantido uma execução única.
</Callout>
