import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { Suspense, lazy, useState } from "react";
import { BottomNav, MonthNav, Sidebar, TopBar } from "@/components/Shell";
import { Toaster } from "@/components/Toast";
import { ErrorState, PageSkeleton } from "@/components/states";
import { formatMonth } from "@/lib/format";
import { useMeta } from "@/lib/queries";
import { useRoute, type Route } from "@/lib/router";
// Cada tela é carregada sob demanda (primeira pintura mais rápida).
const OverviewPage = lazy(() => import("@/pages/Overview").then((m) => ({ default: m.OverviewPage })));
const ExpensesPage = lazy(() => import("@/pages/Expenses").then((m) => ({ default: m.ExpensesPage })));
const FixedPage = lazy(() => import("@/pages/Fixed").then((m) => ({ default: m.FixedPage })));
const InvestmentsPage = lazy(() => import("@/pages/Investments").then((m) => ({ default: m.InvestmentsPage })));
const PlanPage = lazy(() => import("@/pages/Plan").then((m) => ({ default: m.PlanPage })));
const StatusPage = lazy(() => import("@/pages/Status").then((m) => ({ default: m.StatusPage })));

const TITLES: Record<Route, { title: string; subtitle?: string }> = {
  "visao-geral": { title: "Visão geral" },
  gastos: { title: "Gastos" },
  fixos: { title: "Fixos", subtitle: "o que se repete todo mês e o que já está comprometido" },
  investimentos: { title: "Investimentos", subtitle: "quanto você tem, onde está e quanto rendeu" },
  plano: { title: "Plano", subtitle: "sua reserva, sua carteira e o que fazer neste mês" },
  status: { title: "Status", subtitle: "se os dados do banco estão chegando em dia" },
};

export default function App() {
  const route = useRoute();
  const meta = useMeta();
  const [month, setMonth] = useState<string | null>(null);
  const current = month ?? meta.data?.current_month ?? null;
  const demo = meta.data?.demo ?? false;
  const monthly = route === "visao-geral" || route === "gastos";

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex min-h-full">
        <Sidebar route={route} demo={demo} />
        <div className="min-w-0 flex-1">
          <div className="mx-auto w-full max-w-[1440px] px-4 pb-28 pt-6 sm:px-6 md:pb-12 lg:px-10 lg:pt-9">
            <TopBar
              title={TITLES[route].title}
              demo={demo}
              subtitle={monthly && current ? formatMonth(current, "title") : TITLES[route].subtitle}
            >
              {monthly && current && meta.data ? <MonthNav month={current} months={meta.data.months} onChange={setMonth} /> : null}
            </TopBar>
            {meta.isError ? (
              <ErrorState error={meta.error} onRetry={() => meta.refetch()} />
            ) : !current ? (
              <PageSkeleton />
            ) : (
              <AnimatePresence mode="wait" initial={false}>
                <motion.main
                  key={route}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
                >
                  <Suspense fallback={<PageSkeleton />}>
                    {route === "visao-geral" ? <OverviewPage month={current} /> : null}
                    {route === "gastos" ? <ExpensesPage month={current} /> : null}
                    {route === "fixos" ? <FixedPage /> : null}
                    {route === "investimentos" ? <InvestmentsPage /> : null}
                    {route === "plano" ? <PlanPage /> : null}
                    {route === "status" ? <StatusPage /> : null}
                  </Suspense>
                </motion.main>
              </AnimatePresence>
            )}
          </div>
        </div>
        <BottomNav route={route} />
        <Toaster />
      </div>
    </MotionConfig>
  );
}
