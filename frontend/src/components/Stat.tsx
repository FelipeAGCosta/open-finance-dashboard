import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Card } from "./ui/primitives";

/** Indicador: rótulo pequeno, número grande e confiante (figuras proporcionais), linha de apoio. */
export function StatTile({
  label,
  icon,
  value,
  footer,
  className,
  tone,
}: {
  label: string;
  icon?: ReactNode;
  value: ReactNode;
  footer?: ReactNode;
  className?: string;
  tone?: "income" | "expense" | "accent";
}) {
  return (
    <Card className={cn("group relative overflow-hidden p-5 hover:border-border-strong", className)}>
      {tone ? (
        <span
          aria-hidden
          className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full opacity-[0.10] blur-2xl transition-opacity duration-500 group-hover:opacity-20"
          style={{ background: tone === "income" ? "var(--income)" : tone === "expense" ? "var(--expense)" : "var(--accent)" }}
        />
      ) : null}
      <div className="flex items-center gap-2 text-[13px] font-medium text-muted">
        {icon}
        {label}
      </div>
      <div className="mt-2.5 text-[26px] font-semibold leading-tight tracking-[-0.03em] text-text sm:text-[28px]">{value}</div>
      {footer ? <div className="mt-2 text-[12.5px] text-muted">{footer}</div> : null}
    </Card>
  );
}

/** Ícone circular de entrada/saída: a direção também vem pelo ícone, não só pela cor. */
export function FlowIcon({ direction, size = "sm" }: { direction: "in" | "out"; size?: "sm" | "md" }) {
  return (
    <span
      className={cn(
        "grid place-items-center rounded-full",
        size === "sm" ? "h-5 w-5" : "h-8 w-8",
        direction === "in"
          ? "bg-[color-mix(in_oklab,var(--income)_18%,transparent)] text-income"
          : "bg-[color-mix(in_oklab,var(--expense)_18%,transparent)] text-expense",
      )}
      aria-hidden
    >
      <svg viewBox="0 0 16 16" className={size === "sm" ? "h-3 w-3" : "h-4 w-4"} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        {direction === "in" ? <path d="M11 5 5 11M5 6v5h5" /> : <path d="M5 11 11 5M6 5h5v5" />}
      </svg>
    </span>
  );
}
