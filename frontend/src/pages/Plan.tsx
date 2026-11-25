/**
 * Tela Plano, de cima para baixo: Resumo (Reserva e Patrimônio) → O que fazer este mês → Sua carteira × alvo →
 * Calculadora → Ajustar o plano (recolhido). Nenhum formulário do plano aparece aberto por padrão.
 */
import { AlertTriangle, Info } from "lucide-react";
import { motion } from "motion/react";
import { ErrorState, PageSkeleton } from "@/components/states";
import { formatDateTime } from "@/lib/format";
import { usePlan } from "@/lib/queries";
import { navigate } from "@/lib/router";
import { MonthlyTargetForm, PatrimonyTargetForm, ReserveForm, ReturnsForm, RolesForm } from "./plan/Adjust";
import { CalculatorCard } from "./plan/Calculator";
import { HistoryCard, HoldingsCard } from "./plan/Holdings";
import { PortfolioCard } from "./plan/Portfolio";
import { SummaryRow } from "./plan/Summary";
import { ThisMonthCard } from "./plan/ThisMonth";
import { Collapsible } from "./plan/fields";

const rise = { hidden: { opacity: 0, y: 10 }, show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] as const } } };

export function PlanPage() {
  const query = usePlan();
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (!query.data) return <PageSkeleton cards={2} />;
  const plan = query.data;
  const s = plan.settings;
  return (
    <motion.div initial="hidden" animate="show" variants={{ hidden: {}, show: { transition: { staggerChildren: 0.05 } } }} className="space-y-5">
      <motion.div variants={rise} className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-muted">
        <span className="inline-flex items-center gap-1.5">
          <Info className="h-3.5 w-3.5" /> Cálculo a partir das metas que você definiu — não é recomendação de investimento.
        </span>
        {plan.data_stale_hours !== null ? (
          <button type="button" onClick={() => navigate("status")} className="inline-flex items-center gap-1.5 font-medium text-warning hover:underline">
            <AlertTriangle className="h-3.5 w-3.5" /> Dados de {formatDateTime(plan.data_as_of)} (há {plan.data_stale_hours} horas): sincronize no Status
          </button>
        ) : plan.data_as_of ? (
          <span>Dados da Pluggy até {formatDateTime(plan.data_as_of)}</span>
        ) : null}
      </motion.div>

      <motion.div variants={rise}>
        <SummaryRow plan={plan} />
      </motion.div>
      <motion.div variants={rise}>
        <ThisMonthCard plan={plan} />
      </motion.div>
      <motion.div variants={rise} id="plano-carteira" className="scroll-mt-20">
        <PortfolioCard plan={plan} />
      </motion.div>
      <motion.div variants={rise}>
        <CalculatorCard month={plan.month} defaultRate={plan.returns.assumed} />
      </motion.div>

      <motion.div variants={rise} id="plano-ajustar" className="scroll-mt-20">
        <Collapsible id="ajustar" title="Ajustar o plano" hint="Meta de aporte, Reserva, alvos da carteira, Núcleo / Manter / Satélite e meta de rentabilidade.">
          {/* a chave remonta cada formulário com os valores novos depois de salvar ou desfazer */}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <MonthlyTargetForm key={`aporte-${s.aporte_mensal.id}-${s.colchao.id}`} plan={plan} />
            <ReserveForm key={`reserva-${s.reserva.id}`} plan={plan} />
            <PatrimonyTargetForm key={`alvo-${s.alvo_patrimonio.id}`} plan={plan} />
            <RolesForm key={`nucleo-${s.nucleo.id}`} plan={plan} />
            <ReturnsForm key={`rent-${s.rentabilidade.id}`} plan={plan} />
          </div>
        </Collapsible>
      </motion.div>
      <motion.div variants={rise}>
        <Collapsible id="lugares" title="Onde está cada investimento" hint="O que conta como Reserva e o que conta como Patrimônio (automático, com ajuste manual).">
          <HoldingsCard plan={plan} />
        </Collapsible>
      </motion.div>
      <motion.div variants={rise}>
        <Collapsible id="historico" title="Histórico de aportes" hint="Quanto você aportou em cada mês, frente à meta da época.">
          <HistoryCard plan={plan} />
        </Collapsible>
      </motion.div>
    </motion.div>
  );
}
