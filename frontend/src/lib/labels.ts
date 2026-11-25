/** Rótulos em português (sem jargão interno) dos tipos de movimento e da origem da classificação. */
import type { MovementKind } from "./api";

export const MOVEMENT_LABELS: Record<string, string> = {
  despesa: "Despesa",
  receita: "Receita",
  estorno: "Estorno",
  pagamento_fatura: "Pagamento de fatura",
  transferencia_interna: "Entre contas suas",
  aporte: "Aporte",
  resgate: "Resgate",
  renda_investimento: "Renda de investimento",
  reembolso: "Reembolso de gasto",
  emprestimo_concedido: "Empréstimo concedido",
  devolucao_emprestimo: "Devolução de empréstimo",
  transferencia_propria: "Dinheiro meu de outra conta",
};

/** Como a escolha aparece para quem classifica uma entrada ou um Pix enviado. */
export const KIND_CHOICES: Record<MovementKind, { label: string; hint: string }> = {
  receita: { label: "Salário/renda", hint: "Entra nas receitas do mês." },
  reembolso: { label: "Reembolso de gasto", hint: "Alguém devolveu a parte de um gasto: abate a despesa." },
  devolucao_emprestimo: { label: "Devolução de empréstimo", hint: "Dinheiro que você emprestou voltando: neutro." },
  transferencia_propria: { label: "Dinheiro meu de outra conta", hint: "Só mudou de lugar: neutro." },
  despesa: { label: "Gasto", hint: "Entra nas despesas do mês." },
  emprestimo_concedido: { label: "Empréstimo (vou receber de volta)", hint: "Neutro: aparece em Empréstimos em aberto." },
};

export const NEUTRAL_TYPES = new Set(["emprestimo_concedido", "devolucao_emprestimo", "transferencia_propria", "transferencia_interna", "pagamento_fatura"]);

/** Origem automática da categoria, em termos simples. */
export const RULE_LABELS: Record<string, string> = {
  override: "Você escolheu",
  pessoal: "Regra pessoal",
  base: "Regra automática",
  pessoa_fisica: "Pix para pessoa",
  mcc: "Tipo de loja do cartão",
  pluggy: "Categoria do banco",
  a_classificar: "Nenhuma regra reconheceu",
  estorno_da_compra: "Estorno da compra",
  estorno_sem_origem: "Estorno",
};
