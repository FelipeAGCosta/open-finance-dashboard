import { animate, useReducedMotion } from "motion/react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { useEffect, useRef } from "react";
import { formatMoney, formatPercent, type MoneyOptions } from "@/lib/format";
import { useHiddenValues } from "@/lib/preferences";
import { cn } from "@/lib/utils";

/** Valor em R$ que respeita o botão de olho. */
export function Money({ cents, className, ...options }: { cents: number | null | undefined; className?: string } & MoneyOptions) {
  const [hidden] = useHiddenValues();
  return <span className={cn("whitespace-nowrap", className)}>{formatMoney(cents, { ...options, hidden })}</span>;
}

/**
 * Número grande que "conta" até o valor final. Escreve direto no DOM a cada quadro (sem re-render),
 * para ficar fluido; com prefers-reduced-motion mostra o valor final na hora.
 */
export function AnimatedMoney({
  cents,
  className,
  duration = 0.9,
  ...options
}: { cents: number | null | undefined; className?: string; duration?: number } & MoneyOptions) {
  const [hidden] = useHiddenValues();
  const reduced = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const previous = useRef(0);
  const target = cents ?? 0;

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (hidden || reduced || cents === null || cents === undefined) {
      node.textContent = formatMoney(cents, { ...options, hidden });
      previous.current = target;
      return;
    }
    const controls = animate(previous.current, target, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (value) => {
        node.textContent = formatMoney(Math.round(value), options);
      },
    });
    previous.current = target;
    return () => controls.stop();
    // options é um objeto literal novo a cada render; os campos relevantes estão na lista
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, hidden, reduced, duration, options.signed, options.compact]);

  return (
    <span ref={ref} className={cn("whitespace-nowrap", className)}>
      {formatMoney(cents, { ...options, hidden })}
    </span>
  );
}

/** Variação com ícone + sinal + cor (nunca só cor). */
export function Delta({
  cents,
  pct,
  className,
  invert = false,
}: {
  cents?: number | null;
  pct?: number | null;
  className?: string;
  /** Para gastos: subir é ruim. */
  invert?: boolean;
}) {
  const [hidden] = useHiddenValues();
  const value = cents ?? pct ?? 0;
  const direction = value > 0 ? "up" : value < 0 ? "down" : "flat";
  const good = direction === "flat" ? null : (direction === "up") !== invert;
  const Icon = direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : Minus;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 whitespace-nowrap text-[13px] font-medium tnum",
        good === true && "text-positive",
        good === false && "text-negative",
        good === null && "text-muted",
        className,
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {cents !== undefined && cents !== null ? <span>{formatMoney(cents, { signed: true, hidden })}</span> : null}
      {pct !== undefined && pct !== null ? (
        <span className={cents !== undefined && cents !== null ? "text-muted" : undefined}>
          {cents !== undefined && cents !== null ? "(" : ""}
          {formatPercent(pct, { signed: true })}
          {cents !== undefined && cents !== null ? ")" : ""}
        </span>
      ) : null}
    </span>
  );
}
