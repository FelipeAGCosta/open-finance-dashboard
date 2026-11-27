/** Nome do app, igual ao <title> do index.html. */
export const APP_NAME = "Finanças";

/**
 * Título da aba do navegador para a seção aberta: "Gastos · Finanças".
 * Sem seção (texto vazio), fica só o nome do app.
 */
export function pageTitle(section: string): string {
  const name = section.trim();
  return name ? `${name} · ${APP_NAME}` : APP_NAME;
}
