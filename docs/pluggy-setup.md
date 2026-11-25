# Conectar seus dados reais (Pluggy + Meu Pluggy)

O painel lê os dados pela API da [Pluggy](https://pluggy.ai), um agregador de Open Finance. Para uso pessoal,
o caminho é o **Meu Pluggy**: você conecta os seus bancos uma vez e autoriza a sua própria aplicação a ler
esses dados. O guia oficial está em [docs.pluggy.ai](https://docs.pluggy.ai) (procure por "Meu Pluggy" /
uso pessoal); as telas da Pluggy mudam de tempos em tempos, então use os passos abaixo como roteiro.

## 1. Conecte seus bancos no Meu Pluggy

1. Crie uma conta em [meu.pluggy.ai](https://meu.pluggy.ai).
2. Adicione cada banco. O consentimento é dado no app do próprio banco, pelo Open Finance, e é
   **somente leitura** (contas, cartões, investimentos). O consentimento tem validade; quando estiver perto de
   vencer, o painel avisa na tela Status.

## 2. Crie a aplicação no dashboard da Pluggy

1. Entre em [dashboard.pluggy.ai](https://dashboard.pluggy.ai) e crie uma aplicação (a de desenvolvimento basta
   para uso pessoal).
2. Copie o **Client ID** e o **Client Secret** da aplicação.
3. Na aplicação, conecte o conector **MeuPluggy** com a mesma conta do passo 1. Cada banco conectado vira um
   **item**; copie o **item id** de cada um (ele aparece na lista de itens / conexões da aplicação).

## 3. Preencha o `.env`

Na raiz do projeto:

```bash
cp .env.example .env     # no Windows: copy .env.example .env
```

```dotenv
PLUGGY_CLIENT_ID=seu-client-id
PLUGGY_CLIENT_SECRET=seu-client-secret
PLUGGY_ITEM_IDS=item-do-banco-1:nubank,item-do-banco-2
```

- Vários itens: separados por vírgula. Todos são lidos na mesma sincronização e gravados numa transação só.
- `:perfil` depois do id escolhe o [perfil de instituição](institution-profiles.md) (`nubank`, por enquanto).
  Sem sufixo vale o perfil genérico, que funciona com qualquer banco — o perfil só melhora o reconhecimento
  de descrições e a tela "Como no app do banco".
- O `.env` está no `.gitignore`. Variáveis de ambiente do sistema com os mesmos nomes têm precedência.

## 4. Ajuste as suas preferências (opcional)

O arquivo versionado [config/settings.yaml](../config/settings.yaml) traz valores genéricos. Para usar os seus,
crie `data/settings.yaml` (fora do Git) só com o que muda; ele vence campo a campo:

```yaml
salario:
  frequencia: quinzenal   # semanal | quinzenal | mensal
  dia: sexta              # mensal: dia do mês; semanal/quinzenal: dia da semana
plano:
  aporte_mensal: 1500
  reserva: 20000
```

Regras de classificação com nomes de pessoas e lugares vão em `data/regras_pessoais.yaml`
(formato em [config/regras_pessoais.example.yaml](../config/regras_pessoais.example.yaml)). Também dá para
criá-las pela interface: na tela Gastos, mude a categoria de uma transação e escolha "todas desta contraparte".

## 5. Primeira sincronização

```bash
findash sync     # 1ª vez: todo o histórico disponível; depois, janela de 60 dias
findash status   # confere itens, contagens e saldos
findash app      # abre a interface
```

Códigos de saída do `sync`: `0` ok, `1` configuração ou erro inesperado, `2` autenticação recusada pela Pluggy
(credenciais, plano ou trial), `3` outro erro da API (limite de requisições, servidor, rede). Os logs ficam em
`data/logs/`, com segredos mascarados.

## 6. Agende

A rentabilidade da carteira é calculada a partir de **fotos diárias**: quanto mais regular o sync, melhor.
Veja a seção "Agendamento" do [README](../README.md#agendamento) (Agendador de Tarefas no Windows, cron no
Linux/macOS).
