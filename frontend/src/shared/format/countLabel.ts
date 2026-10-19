import { formatQuantity } from './number';

/**
 * A count with its noun in pt-BR, singular only for 1, the number in Brazilian format:
 * "1 produto encontrado", "1.000 produtos encontrados".
 */
export function countLabel(count: number, singular: string, plural: string): string {
  return `${formatQuantity(count)} ${count === 1 ? singular : plural}`;
}
