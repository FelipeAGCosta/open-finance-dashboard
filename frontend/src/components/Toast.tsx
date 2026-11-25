/**
 * Confirmação visual de ações com "Desfazer". Um só aviso por vez (o mais recente), some sozinho.
 */
import { CheckCircle2, AlertTriangle, Undo2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect } from "react";
import { dismissToast, showToast, useToast } from "@/lib/toast";
import { cn } from "@/lib/utils";

const DURATION_MS = 9000;

export function Toaster() {
  const toast = useToast();
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => dismissToast(toast.id), DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [toast]);
  return (
    <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex justify-center px-4 md:bottom-6">
      <AnimatePresence>
        {toast ? (
          <motion.div
            key={toast.id}
            role="status"
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className={cn(
              "pointer-events-auto flex max-w-lg items-center gap-3 rounded-2xl border bg-surface-2 px-4 py-3 shadow-card",
              toast.tone === "error" ? "border-[color-mix(in_oklab,var(--negative)_45%,var(--border))]" : "border-border-strong",
            )}
          >
            {toast.tone === "error" ? (
              <AlertTriangle className="h-4.5 w-4.5 shrink-0 text-negative" />
            ) : (
              <CheckCircle2 className="h-4.5 w-4.5 shrink-0 text-positive" />
            )}
            <div className="min-w-0 text-[13.5px]">
              <p className="font-medium text-text">{toast.title}</p>
              {toast.detail ? <p className="text-[12.5px] text-muted">{toast.detail}</p> : null}
            </div>
            {toast.onUndo ? (
              <button
                type="button"
                onClick={async () => {
                  const undo = toast.onUndo;
                  dismissToast(toast.id);
                  try {
                    await undo?.();
                    showToast({ title: "Desfeito", detail: "Voltou como estava antes." });
                  } catch (error) {
                    showToast({ title: "Não foi possível desfazer", detail: (error as Error).message, tone: "error" });
                  }
                }}
                className="ml-1 inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-semibold text-accent transition-colors hover:bg-accent-soft"
              >
                <Undo2 className="h-3.5 w-3.5" /> Desfazer
              </button>
            ) : null}
            <button
              type="button"
              aria-label="Fechar aviso"
              onClick={() => dismissToast(toast.id)}
              className="shrink-0 rounded-lg p-1 text-muted transition-colors hover:bg-surface-3 hover:text-text"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
