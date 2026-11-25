# Perfis de instituição

O Open Finance padroniza os campos, mas cada banco escreve as descrições do seu jeito, agrupa os investimentos
de um jeito no app e pode mostrar alguns produtos pelo valor líquido de IR. Um **perfil de instituição** reúne
exatamente essas diferenças, para o resto do código continuar genérico.

## O que um perfil define

`backend/findash/institutions/base.py`:

| Membro | Para quê | Padrão (genérico) |
|---|---|---|
| `patterns` | começos de descrição que identificam pagamento de fatura, aporte, resgate, rendimento, estorno | frases comuns ("PAGAMENTO DE FATURA", "APLICACAO", "RESGATE"...) |
| `counterparty_from_description()` | extrair a contraparte embutida na descrição da conta corrente | nenhuma (usa o nome que vem em `paymentData`) |
| `values_net_of_tax()` | produtos que o app mostra pelo líquido de IR | nenhum (tudo pelo bruto) |
| `app_groups` / `app_group()` | grupos da tela de investimentos do app, para "Como no app do banco" | Renda fixa · Bolsa de valores · Tesouro Direto · Outros |

As descrições são comparadas já normalizadas: maiúsculas, sem acento, pontuação virando espaço.

## O exemplo: Nubank

`backend/findash/institutions/nubank.py`:

- a descrição da conta vem como `"Tipo|NOME"` (`"Transferência enviada pelo Pix|FULANO"`): a contraparte é o
  que vem depois do `|`;
- "Dinheiro guardado", "Valor resgatado" e afins são aportes e resgates;
- as **Caixinhas** chegam como CDB/RDB emitido pela Nu Financeira, e o app as mostra pelo líquido de IR, num
  grupo próprio.

## Adicionar um banco

1. Crie `backend/findash/institutions/meubanco.py`:

   ```python
   from findash.institutions.base import DescriptionPatterns, InstitutionProfile


   class MeuBancoProfile(InstitutionProfile):
       key = "meubanco"
       name = "Meu Banco"
       patterns = DescriptionPatterns(
           investment_out=("APLICACAO", "INVESTIMENTO AUTOMATICO"),
           investment_in=("RESGATE", "RESGATE AUTOMATICO"),
       )
   ```

   Sobrescreva só o que for diferente do genérico.
2. Registre em `backend/findash/institutions/__init__.py`, na tupla de `PROFILES`.
3. Use no `.env`: `PLUGGY_ITEM_IDS=id-do-item:meubanco`.
4. Escreva um teste com descrições **inventadas** no formato do banco (veja `tests/test_classify.py`). Nunca cole
   JSON real da sua conta em fixtures.

Para descobrir os padrões, rode `findash a-classificar` depois de um sync: ele lista as despesas sem categoria
agrupadas por contraparte, e `findash classificar` mostra quantos créditos de investimento ficaram sem par.
