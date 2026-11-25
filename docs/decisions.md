# Decisões técnicas

Registro curto das escolhas que não são óbvias olhando só o código.

## Dinheiro em centavos inteiros

**Decisão:** todo valor monetário é `int` em centavos (`amount_normalized_cents`, `balance_cents`...).
**Por quê:** `float` acumula erro (`0.1 + 0.2`), e `Decimal` no SQLite vira texto ou `REAL`. Inteiros somam
exatamente em SQL e em Python. Percentuais e preços unitários (que precisam de casas decimais) usam `Decimal`
na lógica e `Numeric` no banco. O valor exatamente como veio da API fica guardado no JSON bruto.

## Convenção única de sinal

**Decisão:** `amount_normalized_cents` é negativo quando o dinheiro sai (compra no cartão, Pix enviado) e
positivo quando entra, independentemente do tipo de conta.
**Por quê:** a Pluggy usa sinais diferentes para conta corrente e cartão. Normalizar uma vez no sync tira essa
regra de todo o resto do código.

## Sync idempotente e atômico

**Decisão:** buscar tudo antes de gravar e aplicar numa única transação; upsert pelo id da Pluggy.
**Por quê:** uma falha de rede no meio da busca não pode deixar o banco pela metade (contas novas sem
transações, fotos de um item e não de outro). Rodar o sync de novo é sempre seguro: não duplica nada.
Pendentes que somem da API não são apagadas: viram "substituída" (achamos a versão confirmada, com outro id) ou
"removida" (cancelada) e deixam de contar nos totais.

## Pareamento de fatura

**Decisão:** o pagamento da fatura na conta corrente e o "pagamento recebido" no cartão são classificados como
`pagamento_fatura` e pareados (mesmo valor, até 5 dias de distância).
**Por quê:** sem isso, cada compra no cartão contaria duas vezes — como compra e como pagamento da fatura. As
despesas são as compras; o pagamento é só dinheiro mudando de lugar.

## Patrimônio = só o investido, com "em trânsito"

**Decisão:** o patrimônio total é a carteira (como o app do banco mostra) mais as compras em trânsito. Saldo da
conta e fatura aparecem à parte.
**Por quê:** o saldo da conta oscila com o calendário de salário e fatura, o que tornava o gráfico ruidoso. E
uma compra de ação sai da conta em D0 mas só aparece na carteira em D+2: sem o "em trânsito", o patrimônio
cairia e voltaria sem motivo. O pareamento procura o aumento de posição (cotas novas, ativo novo ou soma de
várias posições do mesmo dia) numa janela de dias úteis; se nada aparecer em 5 dias úteis, o valor sai sozinho.
"Já chegou" e "Ignorar" resolvem à mão.

## Origem dos resgates

**Decisão:** cada crédito de resgate ou venda na conta é ligado ao ativo de onde saiu — primeiro pela queda de
quantidade/saldo entre fotos diárias, depois pelas vendas registradas — numa janela de D−1 a D+3 dias úteis,
com tolerância de 3% (IR, taxas, preço).
**Por quê:** "resgatei R$ 3.000" é pouco útil; "resgatei R$ 3.000 do CDB" explica a variação da carteira e
alimenta a rentabilidade.

## Classificação por regras em camadas, recalculada do zero

**Decisão:** a classificação é uma camada derivada, apagada e recalculada a cada sync, com prioridade fixa
(manual > pessoal > base > pessoa física > MCC > Pluggy > "A classificar").
**Por quê:** regras mudam o tempo todo (o usuário corrige uma categoria, uma regra base melhora). Recalcular do
zero garante o mesmo resultado para os mesmos dados e torna cada decisão explicável: a tela mostra qual regra
classificou cada transação. As escolhas do usuário ficam em tabelas próprias e nunca são sobrescritas.

## TWR × XIRR

**Decisão:** mostrar os dois.
**Por quê:** respondem perguntas diferentes. O **TWR** (retorno ponderado pelo tempo) encadeia o retorno de cada
trecho entre fotos descontando aportes e resgates: mede os investimentos e é o número comparável com o CDI. O
**XIRR** (taxa interna de retorno com datas) mede o resultado do investidor: aportar antes de uma alta aumenta
o XIRR e não muda o TWR. Mostrar só um deles esconde metade da história.

## Rebalanceamento só com aportes

**Decisão:** o plano nunca sugere venda. O aporte do mês vai primeiro para a Reserva (se estiver abaixo do
valor), depois para as classes do Patrimônio mais abaixo do alvo, nivelando as distâncias ("water filling").
FIIs, ações "mantidas" e satélite nunca recebem sugestão.
**Por quê:** vender gera IR e custo; para quem aporta todo mês, direcionar o dinheiro novo corrige a alocação com
o tempo. É cálculo a partir das metas do usuário, não recomendação.

## Metas com histórico de vigência

**Decisão:** cada mudança de meta é uma linha nova com o mês a partir do qual vale.
**Por quê:** se a meta de aporte sobe em agosto, os meses anteriores continuam sendo avaliados pela meta da
época. Desfazer é apagar a linha recém-criada.

## Perfil de instituição

**Decisão:** isolar o que é específico de banco numa classe pequena (`institutions/`), escolhida por item.
**Por quê:** o Open Finance padroniza campos, não texto livre. Sem o perfil, o código geral ficaria cheio de
`if banco == ...`. Ver [institution-profiles.md](institution-profiles.md).

## Agenda do salário configurável

**Decisão:** a periodicidade (semanal, quinzenal, mensal), o dia e a tolerância de atraso ficam em
`settings.yaml`; a regra detectada guarda a agenda.
**Por quê:** "esperado × recebido" só faz sentido com a agenda certa, e nos salários semanais e quinzenais
alguns meses têm um pagamento a mais — que o plano pode somar à meta de aporte.

## Tudo local, sem conta e sem nuvem

**Decisão:** SQLite num arquivo, servidor só em `127.0.0.1`, proteção contra DNS rebinding e CSRF.
**Por quê:** é o histórico financeiro de uma pessoa. O custo (sem acesso pelo celular fora de casa) é aceitável
para o objetivo.
