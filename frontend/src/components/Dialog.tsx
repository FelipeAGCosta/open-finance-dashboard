/**
 * Diálogo modal simples (Esc ou clique fora fecham; o foco vai para a primeira opção) e o diálogo
 * de escopo das ações da lista: "Só esta" ou "Esta e todas desta contraparte".
 */
import { Layers, MousePointerClick, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

export function Dialog({
  open,
  title,
  description,
  onClose,
  children,
  size = "md",
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /** lg: formulários maiores (rola por dentro em telas baixas). */
  size?: "md" | "lg";
}) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const first = panel.current?.querySelector<HTMLElement>("[data-autofocus], button:not([aria-label='Fechar'])");
    first?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [open, onClose]);
  return createPortal(
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-[70] flex items-end justify-center bg-black/45 p-3 backdrop-blur-[2px] sm:items-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(event) => event.target === event.currentTarget && onClose()}
        >
          <motion.div
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            initial={{ opacity: 0, y: 14, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className={cn(
              "w-full rounded-[var(--radius-card)] border border-border-strong bg-surface p-5 shadow-card",
              size === "lg" ? "max-h-[92vh] max-w-2xl overflow-y-auto" : "max-w-md",
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-[16px] font-semibold tracking-[-0.01em]">{title}</h2>
                {description ? <div className="mt-1 text-[13px] leading-relaxed text-muted">{description}</div> : null}
              </div>
              <button type="button" aria-label="Fechar" onClick={onClose} className="rounded-lg p-1 text-muted hover:bg-surface-2 hover:text-text">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-4">{children}</div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}

export type Scope = "one" | "counterparty";

/** Pergunta o escopo da ação. A segunda opção só aparece quando há contraparte identificada. */
export function ScopeDialog({
  open,
  title,
  change,
  counterparty,
  allowCounterparty,
  counterpartyHint,
  onChoose,
  onClose,
}: {
  open: boolean;
  title: string;
  change: ReactNode;
  counterparty: string | null;
  allowCounterparty: boolean;
  counterpartyHint?: string;
  onChoose: (scope: Scope) => void;
  onClose: () => void;
}) {
  return (
    <Dialog open={open} title={title} description={change} onClose={onClose}>
      <div className="space-y-2">
        <ScopeOption
          icon={<MousePointerClick className="h-4 w-4" />}
          title="Só esta"
          detail="Muda apenas esta transação."
          onClick={() => onChoose("one")}
        />
        {allowCounterparty ? (
          <ScopeOption
            icon={<Layers className="h-4 w-4" />}
            title={`Esta e todas de ${counterparty ?? "esta contraparte"}`}
            detail={counterpartyHint ?? "Vale para as passadas e para as que vierem; dá para desfazer."}
            onClick={() => onChoose("counterparty")}
          />
        ) : null}
      </div>
      <button type="button" onClick={onClose} className="mt-3 w-full rounded-xl py-2 text-[13px] text-muted hover:bg-surface-2 hover:text-text">
        Cancelar
      </button>
    </Dialog>
  );
}

function ScopeOption({ icon, title, detail, onClick }: { icon: ReactNode; title: string; detail: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-start gap-3 rounded-xl border border-border bg-surface-2 px-3.5 py-3 text-left transition-colors",
        "hover:border-[color-mix(in_oklab,var(--accent)_45%,var(--border))] hover:bg-surface-3",
      )}
    >
      <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">{icon}</span>
      <span className="min-w-0">
        <span className="block break-words text-[14px] font-medium text-text">{title}</span>
        <span className="block text-[12.5px] text-muted">{detail}</span>
      </span>
    </button>
  );
}
