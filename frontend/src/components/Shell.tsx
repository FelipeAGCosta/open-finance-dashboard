import { ChevronLeft, ChevronRight, Eye, EyeOff, LayoutDashboard, Moon, Receipt, Repeat, Activity, Sun, Target, TrendingUp } from "lucide-react";
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { formatMonth } from "@/lib/format";
import { useHiddenValues, useTheme } from "@/lib/preferences";
import type { Route } from "@/lib/router";
import { cn } from "@/lib/utils";
import { LogoMark } from "./Logo";
import { Select } from "./ui/select";
import { Badge, Button } from "./ui/primitives";

const NAV: { route: Route; label: string; short: string; icon: typeof LayoutDashboard }[] = [
  { route: "visao-geral", label: "Visão geral", short: "Início", icon: LayoutDashboard },
  { route: "gastos", label: "Gastos", short: "Gastos", icon: Receipt },
  { route: "fixos", label: "Fixos", short: "Fixos", icon: Repeat },
  { route: "investimentos", label: "Investimentos", short: "Invest.", icon: TrendingUp },
  { route: "plano", label: "Plano", short: "Plano", icon: Target },
  { route: "status", label: "Status", short: "Status", icon: Activity },
];

export function Sidebar({ route, demo }: { route: Route; demo: boolean }) {
  return (
    <div className="hidden shrink-0 border-r border-border bg-[color-mix(in_oklab,var(--surface)_70%,transparent)] md:block md:w-[76px] lg:w-[244px]">
    <aside className="sticky top-0 flex h-screen flex-col px-3 py-5">
      <div className="mb-8 flex items-center gap-3 px-2.5">
        <LogoMark size={34} />
        <div className="hidden lg:block">
          <p className="text-[15px] font-semibold tracking-[-0.02em]">Finanças</p>
          <p className="text-[11.5px] text-muted">só neste computador</p>
        </div>
      </div>
      <nav className="flex flex-1 flex-col gap-1" aria-label="Seções">
        {NAV.map(({ route: target, label, icon: Icon }) => {
          const active = target === route;
          return (
            <a
              key={target}
              href={`#/${target}`}
              aria-current={active ? "page" : undefined}
              title={label}
              className={cn(
                "group relative flex h-11 items-center gap-3 rounded-xl px-3 text-[14px] font-medium transition-colors duration-200",
                "justify-center lg:justify-start",
                active ? "text-text" : "text-muted hover:bg-surface-2 hover:text-text",
              )}
            >
              {active ? (
                <motion.span
                  layoutId="nav-active"
                  className="absolute inset-0 rounded-xl border border-border bg-surface-2"
                  transition={{ type: "spring", stiffness: 420, damping: 36 }}
                />
              ) : null}
              <Icon className={cn("relative h-[18px] w-[18px]", active && "text-accent")} strokeWidth={2} />
              <span className="relative hidden lg:inline">{label}</span>
            </a>
          );
        })}
      </nav>
      {demo ? (
        <div className="mt-4 hidden rounded-xl border border-border bg-accent-soft px-3 py-2.5 text-[12px] leading-snug text-text-2 lg:block">
          <span className="font-semibold text-accent">Modo demonstração.</span> Todos os dados são fictícios.
        </div>
      ) : null}
    </aside>
    </div>
  );
}

export function BottomNav({ route }: { route: Route }) {
  return (
    <nav
      aria-label="Seções"
      className="fixed inset-x-0 bottom-0 z-40 flex border-t border-border bg-[color-mix(in_oklab,var(--surface)_88%,transparent)] px-1 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden"
    >
      {NAV.map(({ route: target, label, short, icon: Icon }) => (
        <a
          aria-label={label}
          key={target}
          href={`#/${target}`}
          aria-current={target === route ? "page" : undefined}
          className={cn(
            "flex flex-1 flex-col items-center gap-1 py-2 text-[10.5px] font-medium",
            target === route ? "text-accent" : "text-muted",
          )}
        >
          <Icon className="h-5 w-5" />
          {short}
        </a>
      ))}
    </nav>
  );
}

export function TopBar({ title, subtitle, children, demo }: { title: string; subtitle?: ReactNode; children?: ReactNode; demo: boolean }) {
  const [hidden, toggleHidden] = useHiddenValues();
  const [theme, toggleTheme] = useTheme();
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2.5">
          <h1 className="text-[26px] font-semibold tracking-[-0.03em] sm:text-[30px]">{title}</h1>
          {demo ? (
            <Badge tone="accent" className="lg:hidden">
              demonstração
            </Badge>
          ) : null}
        </div>
        {subtitle ? <p className="mt-1 text-[14px] text-muted">{subtitle}</p> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {children}
        <Button
          variant="secondary"
          size="icon"
          onClick={toggleHidden}
          aria-pressed={hidden}
          aria-label={hidden ? "Mostrar valores" : "Esconder valores"}
          title={hidden ? "Mostrar valores" : "Esconder valores"}
        >
          {hidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </Button>
        <Button
          variant="secondary"
          size="icon"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Usar tema claro" : "Usar tema escuro"}
          title={theme === "dark" ? "Tema claro" : "Tema escuro"}
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>
    </header>
  );
}

export function MonthNav({ month, months, onChange }: { month: string; months: string[]; onChange: (month: string) => void }) {
  const index = months.indexOf(month);
  const older = index >= 0 ? months[index + 1] : undefined; // months vem do mais recente para o mais antigo
  const newer = index > 0 ? months[index - 1] : undefined;
  return (
    <div className="flex items-center gap-1.5">
      <Button variant="secondary" size="icon" disabled={!older} onClick={() => older && onChange(older)} aria-label="Mês anterior">
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <Select
        label="Mês"
        value={month}
        onValueChange={onChange}
        className="w-[196px]"
        options={months.map((m) => ({ value: m, label: formatMonth(m, "title") }))}
      />
      <Button variant="secondary" size="icon" disabled={!newer} onClick={() => newer && onChange(newer)} aria-label="Próximo mês">
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}
