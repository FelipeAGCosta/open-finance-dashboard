/**
 * Ajuda para leigos: ícone "?" ao lado de um termo técnico, com a explicação em uma frase
 * (aparece ao passar o mouse, ao focar com o teclado ou ao tocar), e o bloco recolhível
 * "Ver como calculamos".
 */
import { ChevronDown, HelpCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useId, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Term({ children, help, className }: { children: ReactNode; help: string; className?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className={cn("relative inline-flex items-center gap-1", className)}>
      {children}
      <button
        type="button"
        aria-label="O que é isso?"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        className="inline-grid h-4 w-4 place-items-center rounded-full text-muted transition-colors hover:text-accent"
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </button>
      <AnimatePresence>
        {open ? (
          <motion.span
            id={id}
            role="tooltip"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="absolute left-0 top-full z-50 mt-1.5 w-64 rounded-xl border border-border-strong bg-surface-2 px-3 py-2 text-left text-[12.5px] font-normal normal-case leading-snug tracking-normal text-text-2 shadow-card"
          >
            {help}
          </motion.span>
        ) : null}
      </AnimatePresence>
    </span>
  );
}

/** "Ver como calculamos": fórmulas e detalhes recolhidos por padrão. */
export function HowCalculated({ children, label = "Ver como calculamos", className }: { children: ReactNode; label?: string; className?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className={cn("mt-4", className)}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 text-[12.5px] font-medium text-muted transition-colors hover:text-text"
      >
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform duration-200", open && "rotate-180")} />
        {open ? "Esconder a conta" : label}
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            id={id}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="mt-2 rounded-xl border border-border bg-surface-2/60 px-3.5 py-3 text-[12.5px] leading-relaxed text-text-2">
              {children}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

/** Linha de conta: "+ Receitas já recebidas ........ R$ 1.234,00". */
export function CalcLine({ sign, label, value, strong }: { sign?: "+" | "−" | "=" | "×"; label: ReactNode; value: ReactNode; strong?: boolean }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 py-0.5", strong && "mt-1 border-t border-border pt-1.5 font-semibold text-text")}>
      <span className="min-w-0">
        {sign ? <span className="mr-1.5 inline-block w-3 text-muted">{sign}</span> : null}
        {label}
      </span>
      <span className="shrink-0 whitespace-nowrap tnum">{value}</span>
    </div>
  );
}
