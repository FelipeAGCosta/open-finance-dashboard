import { AlertTriangle, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";
import { Button, Card, Skeleton } from "./ui/primitives";
import { cn } from "@/lib/utils";

export function EmptyState({
  icon,
  title,
  children,
  className,
}: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-10 text-center", className)}>
      <div className="mb-4 grid h-12 w-12 place-items-center rounded-2xl border border-border bg-surface-2 text-accent">
        {icon}
      </div>
      <p className="text-[15px] font-semibold text-text">{title}</p>
      {children ? <div className="mt-1.5 max-w-md text-[13px] leading-relaxed text-muted">{children}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Erro inesperado.";
  return (
    <Card className="border-[color-mix(in_oklab,var(--negative)_35%,var(--border))]">
      <div className="flex flex-col items-center px-6 py-12 text-center">
        <div className="mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-[color-mix(in_oklab,var(--negative)_14%,transparent)] text-negative">
          <AlertTriangle className="h-5 w-5" />
        </div>
        <p className="text-[15px] font-semibold">Não foi possível carregar</p>
        <p className="mt-1 max-w-md text-[13px] text-muted">{message}</p>
        {onRetry ? (
          <Button className="mt-5" size="sm" onClick={onRetry}>
            <RotateCcw className="h-3.5 w-3.5" /> Tentar de novo
          </Button>
        ) : null}
      </div>
    </Card>
  );
}

/** Esqueleto com a mesma geometria da página, para não "pular" quando os dados chegam. */
export function PageSkeleton({ cards = 4 }: { cards?: number }) {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="Carregando">
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: cards }).map((_, i) => (
          <Card key={i} className="p-6">
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="mt-4 h-8 w-36" />
            <Skeleton className="mt-3 h-3 w-20" />
          </Card>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <Card className="p-6 xl:col-span-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="mt-6 h-[260px] w-full rounded-xl" />
        </Card>
        <Card className="p-6">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="mx-auto mt-8 h-44 w-44 rounded-full" />
        </Card>
      </div>
    </div>
  );
}
