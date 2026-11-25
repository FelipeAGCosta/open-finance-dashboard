# Como este projeto foi construído

Este painel foi desenvolvido por mim usando o **Claude Code** (agente de programação da Anthropic) como
ferramenta, dentro de um fluxo que padronizei num kit próprio, o **AI Engineering Starter Kit**. A ideia
central: o agente escreve código rápido, mas quem decide o produto, revisa e aprova sou eu — e o processo deixa
isso explícito em vez de depender de boa vontade.

Os exemplos abaixo são **genéricos**: não reproduzem a memória nem as conversas reais do projeto.

## 1. Perfil de projeto

Ao iniciar, o kit gera um arquivo de instruções para o agente (`AGENTS.md`) a partir de **perfis** combináveis
(por exemplo: Python + API, frontend React, pipeline de dados). O perfil define:

- o que o agente pode alterar sem perguntar e o que exige aprovação (migrations, dependências, CI, segredos);
- quais comandos validam cada parte (`pytest`, `ruff`, `npm run typecheck`...);
- regras de escopo: mudança mínima, não refatorar o que não foi pedido, preservar trabalho não commitado.

## 2. Trabalho em rodadas pequenas

Cada mudança começa com um pedido claro e termina com evidência:

```text
Pedido:   "Na tela Gastos, permitir marcar um gasto como extraordinário, só este ou toda a contraparte,
           com desfazer."
Agente:   lê o código existente, propõe a menor mudança, implementa, escreve os testes.
Validação: pytest (backend) + vitest/typecheck/lint (frontend) rodados de verdade, com o resultado no relatório.
Eu:       reviso o diff e o comportamento, aprovo ou peço ajuste.
```

O relatório final usa rótulos explícitos — `PASS`, `FAIL`, `NOT EXECUTED` — para que "deve funcionar" nunca se
passe por "testado".

## 3. Checagens obrigatórias antes de publicar

Commit e push passam por um único script que:

1. recusa branches protegidas (`main`) e remotos não aprovados;
2. roda uma **varredura de segredos** no que vai para o commit;
3. roda as verificações aprovadas (testes, lint, typecheck, build) e aborta se alguma falhar;
4. faz stage só dos arquivos da tarefa (nada de `git add -A`) e nunca usa `--force` nem `--no-verify`.

Merge para `main` continua sendo decisão humana, via pull request.

## 4. Memória de projeto com evidência

Entre sessões, o contexto vive numa memória versionada no próprio repositório, com tipos diferentes de
registro:

| Tipo | Quando entra | Exemplo genérico |
|---|---|---|
| **Aprendizado** | só com evidência verificável (teste que passou, commit) | "A API devolve a compra pendente e a confirmada com ids diferentes; o sync casa as duas por valor e data — `test: test_pending_replaced`." |
| **Hipótese** | observação ainda não confirmada | "Talvez o histórico disponível seja menor que 12 meses para alguns bancos." |
| **Decisão** | nasce *proposta*; só vale com aprovação explícita registrada | "Patrimônio total passa a excluir o saldo da conta corrente." |
| **Estado atual** | o que está em andamento e o que está bloqueado | "Branch de trabalho X, aguardando revisão." |

Isso evita dois problemas comuns com agentes: repetir erros já resolvidos e tratar suposições como fatos.

## 5. Revisores especializados

Para mudanças maiores, o kit oferece revisores somente leitura (arquitetura, contratos entre módulos, regressão,
segurança). Eles dão **opinião técnica**, não aprovação: a decisão continua humana.

## O que isso mudou na prática

- Testes acompanham cada funcionalidade (mais de 270 no repositório, todos com dados sintéticos).
- Nenhum segredo ou dado pessoal entrou no Git — este repositório público, inclusive, foi gerado do zero a
  partir do projeto pessoal, com varredura de segredos e de termos sensíveis antes do primeiro push.
- As decisões técnicas ficaram registradas ([decisions.md](decisions.md)) em vez de perdidas em conversas.
