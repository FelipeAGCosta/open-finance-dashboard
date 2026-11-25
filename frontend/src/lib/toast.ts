/** Aviso de confirmação com "Desfazer": um só por vez (o mais recente). */
import { useSyncExternalStore } from "react";

export interface ToastMessage {
  id: number;
  title: string;
  detail?: string;
  tone?: "success" | "error";
  onUndo?: () => Promise<unknown> | void;
}

let current: ToastMessage | null = null;
let seq = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function showToast(message: Omit<ToastMessage, "id">): void {
  current = { ...message, id: ++seq };
  emit();
}

export function dismissToast(id?: number): void {
  if (id === undefined || current?.id === id) {
    current = null;
    emit();
  }
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export function useToast(): ToastMessage | null {
  return useSyncExternalStore(subscribe, () => current, () => null);
}
