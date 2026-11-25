/** Patrimônio total (o mesmo nome e o mesmo número em todas as telas) e a linha "Em trânsito". */
import { Check, Truck, X } from "lucide-react";
import { useState } from "react";
import { Term } from "@/components/Help";
import { Money } from "@/components/Money";
import { Select } from "@/components/ui/select";
import { Button } from "@/components/ui/primitives";
import type { InTransitAction, InTransitItem, Wealth } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import { GLOSSARY } from "@/lib/glossary";
import { useHiddenValues } from "@/lib/preferences";
import { useInTransitMutation, useUndo } from "@/lib/queries";
import { showToast } from "@/lib/toast";
import { cn } from "@/lib/utils";

export const WEALTH_LABEL = "Patrimônio total";

export function WealthTerm({ className }: { className?: string }) {
  return (
    <Term help={GLOSSARY.patrimonioTotal}>
      <span className={className}>{WEALTH_LABEL}</span>
    </Term>
  );
}

/** "Em trânsito: R$ X" com o que está liquidando; não mostra nada quando não há compra em trânsito. */
export function InTransitNote({ wealth, className }: { wealth: Wealth | null | undefined; className?: string }) {
  const [hidden] = useHiddenValues();
  const transit = wealth?.in_transit;
  if (!transit || transit.cents <= 0) return null;
  const many = transit.items.length > 1;
  const items = transit.items
    .map((i) => `${i.description} de ${formatDate(i.date, "day")}${many ? ` (${formatMoney(i.cents, { hidden })})` : ""}`)
    .join("; ");
  return (
    <div className={cn("text-[12.5px] text-text-2", className)}>
      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
        <Truck aria-hidden className="h-3.5 w-3.5 shrink-0 text-accent" />
        <span className="inline-flex items-center">
          <Term help={GLOSSARY.emTransito}>
            <span>Em trânsito</span>
          </Term>
          :
        </span>
        <Money cents={transit.cents} className="font-medium text-text tnum" />
        <span className="text-muted">· {items}, somada até aparecer na carteira</span>
      </p>
      <ul className="mt-1.5 space-y-1.5">
        {transit.items.map((item) => (
          <InTransitActions key={item.id} item={item} assets={transit.assets} label={many ? `${item.description} de ${formatDate(item.date, "day")}` : null} />
        ))}
      </ul>
    </div>
  );
}

/** "Já chegou (é o ativo X)" ou "Ignorar"; a escolha fica gravada e pode ser desfeita no aviso. */
function InTransitActions({ item, assets, label }: { item: InTransitItem; assets: { id: string; label: string }[]; label: string | null }) {
  const mutation = useInTransitMutation();
  const undo = useUndo();
  const [asset, setAsset] = useState(item.suggestion?.id ?? "");
  const [picking, setPicking] = useState(false);
  const assetLabel = assets.find((a) => a.id === asset)?.label ?? item.suggestion?.label;

  const choose = (action: InTransitAction, investmentId?: string) =>
    mutation.mutate(
      { id: item.id, action, investmentId },
      {
        onSuccess: (result) =>
          showToast({
            title: action === "chegou" ? `Já chegou: ${assetLabel}` : "Compra ignorada",
            detail: action === "chegou" ? "Saiu do em trânsito; o valor já está na carteira." : "Não soma mais ao patrimônio.",
            onUndo: () => undo(result.undo),
          }),
        onError: (error) => showToast({ title: "Não foi possível salvar", detail: error.message, tone: "error" }),
      },
    );

  return (
    <li className="flex flex-wrap items-center gap-1.5 pl-5">
      {label ? <span className="mr-1 text-muted">{label}:</span> : null}
      {picking ? (
        <>
          <Select
            size="sm"
            label="Qual ativo chegou"
            placeholder="Qual ativo chegou?"
            value={asset}
            onValueChange={setAsset}
            className="w-[190px]"
            options={assets.map((a) => ({ value: a.id, label: a.label }))}
          />
          <Button size="sm" disabled={!asset || mutation.isPending} onClick={() => choose("chegou", asset)}>
            <Check aria-hidden className="h-3.5 w-3.5" />
            Já chegou{assetLabel && asset ? ` (é o ${assetLabel})` : ""}
          </Button>
        </>
      ) : !item.suggestion ? (
        <Button size="sm" onClick={() => setPicking(true)}>
          <Check aria-hidden className="h-3.5 w-3.5" />
          Já chegou…
        </Button>
      ) : (
        <>
          <Button size="sm" disabled={mutation.isPending} onClick={() => choose("chegou", asset)}>
            <Check aria-hidden className="h-3.5 w-3.5" />
            Já chegou (é o {assetLabel})
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setPicking(true)}>
            outro ativo
          </Button>
        </>
      )}
      <Button size="sm" variant="ghost" disabled={mutation.isPending} onClick={() => choose("ignorar")}>
        <X aria-hidden className="h-3.5 w-3.5" />
        Ignorar
      </Button>
    </li>
  );
}
