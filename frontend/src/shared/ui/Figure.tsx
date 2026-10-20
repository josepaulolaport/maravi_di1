import { Text, type TextProps } from '@mantine/core';

import { UNAVAILABLE } from '@/shared/format';

interface FigureProps extends TextProps {
  /** The formatted figure, or UNAVAILABLE ("—"). */
  text: string;
  /** What "—" means here, as its tooltip: unavailable unless said otherwise. */
  missing?: string;
}

/**
 * A figure shown as text. It never wraps, so a sign stays with its number (QA 2026-10-19 #2),
 * and "—" says why there is no value: `null` is unavailable, never zero.
 */
export function Figure({ text, missing = 'Indisponível', ...props }: FigureProps) {
  return (
    <Text
      component="span"
      inherit
      style={{ whiteSpace: 'nowrap' }}
      {...(text === UNAVAILABLE ? { title: missing } : {})}
      {...props}
    >
      {text}
    </Text>
  );
}
