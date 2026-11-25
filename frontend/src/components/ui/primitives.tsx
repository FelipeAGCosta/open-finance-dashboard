/** Componentes base no estilo shadcn/ui (Tailwind + tokens do tema). */
import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-card)] border border-border bg-surface shadow-card",
        "transition-[border-color,box-shadow] duration-300",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 px-6 pt-5", className)}>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-text">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-6 pb-6 pt-4", className)} {...props} />;
}

type ButtonVariant = "primary" | "secondary" | "ghost";

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: "sm" | "md" | "icon" }
>(function Button({ className, variant = "secondary", size = "md", ...props }, ref) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex select-none items-center justify-center gap-2 rounded-xl font-medium",
        "transition-[background-color,color,transform,box-shadow] duration-200 active:scale-[0.97]",
        "disabled:pointer-events-none disabled:opacity-50",
        size === "md" && "h-10 px-4 text-sm",
        size === "sm" && "h-8 px-3 text-[13px]",
        size === "icon" && "h-9 w-9",
        variant === "primary" && "bg-accent text-accent-fg shadow-[0_6px_20px_-8px_var(--accent)] hover:brightness-110",
        variant === "secondary" && "border border-border bg-surface-2 text-text hover:border-border-strong hover:bg-surface-3",
        variant === "ghost" && "text-text-2 hover:bg-surface-2 hover:text-text",
        className,
      )}
      {...props}
    />
  );
});

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cn(
        "h-10 w-full rounded-xl border border-border bg-surface-2 px-3 text-sm text-text placeholder:text-muted",
        "transition-colors duration-200 hover:border-border-strong focus:border-accent focus:outline-none",
        className,
      )}
      {...props}
    />
  );
});

export function Badge({
  className,
  tone = "neutral",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: "neutral" | "accent" | "positive" | "negative" | "warning" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium leading-5",
        tone === "neutral" && "bg-surface-3 text-text-2",
        tone === "accent" && "bg-accent-soft text-accent",
        tone === "positive" && "bg-[color-mix(in_oklab,var(--positive)_14%,transparent)] text-positive",
        tone === "negative" && "bg-[color-mix(in_oklab,var(--negative)_14%,transparent)] text-negative",
        tone === "warning" && "bg-[color-mix(in_oklab,var(--warning)_16%,transparent)] text-warning",
        className,
      )}
      {...props}
    />
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("skeleton rounded-lg", className)} />;
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-xl border border-border bg-surface-2 p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          role="radio"
          aria-checked={option.value === value}
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-[10px] px-3 py-1.5 text-[13px] font-medium transition-all duration-200",
            option.value === value ? "bg-surface text-text shadow-card" : "text-muted hover:text-text",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
