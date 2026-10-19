/** "1 produto encontrado" / "4 produtos encontrados" (pt-BR: singular only for 1). */
export function countLabel(count: number, singular: string, plural: string): string {
  return `${String(count)} ${count === 1 ? singular : plural}`;
}
