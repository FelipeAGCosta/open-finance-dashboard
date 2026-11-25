import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: ReactNode;
}

/** Select acessível (Radix) no estilo shadcn/ui. A lista abre acima de tudo, inclusive dos diálogos (z-[70]). */
export function Select({
  value,
  onValueChange,
  options,
  label,
  placeholder,
  className,
  size = "md",
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  label: string;
  placeholder?: string;
  className?: string;
  size?: "sm" | "md";
}) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange}>
      <SelectPrimitive.Trigger
        aria-label={label}
        className={cn(
          "inline-flex items-center justify-between gap-2 rounded-xl border border-border bg-surface-2 text-left text-text",
          "transition-colors duration-200 hover:border-border-strong data-[placeholder]:text-muted",
          size === "md" ? "h-10 px-3 text-sm" : "h-8 px-2.5 text-[13px]",
          className,
        )}
      >
        <span className="truncate">
          <SelectPrimitive.Value placeholder={placeholder} />
        </span>
        <SelectPrimitive.Icon>
          <ChevronDown className="h-4 w-4 shrink-0 text-muted" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={6}
          className={cn(
            "z-[90] max-h-[min(360px,var(--radix-select-content-available-height))] min-w-[var(--radix-select-trigger-width)]",
            "overflow-hidden rounded-xl border border-border-strong bg-surface-2 shadow-card",
          )}
        >
          <SelectPrimitive.Viewport className="p-1">
            {options.map((option) => (
              <SelectPrimitive.Item
                key={option.value}
                value={option.value}
                className={cn(
                  "relative flex cursor-pointer select-none items-center rounded-lg py-2 pl-8 pr-3 text-sm text-text outline-none",
                  "data-[highlighted]:bg-surface-3",
                )}
              >
                <SelectPrimitive.ItemIndicator className="absolute left-2.5">
                  <Check className="h-4 w-4 text-accent" />
                </SelectPrimitive.ItemIndicator>
                <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
