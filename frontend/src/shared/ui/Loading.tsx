import { type MantineSpacing, Skeleton, Stack, VisuallyHidden } from '@mantine/core';

interface LoadingProps {
  /** pt-BR, e.g. "Carregando carteira": the name screen readers announce. */
  label: string;
  /** One skeleton per height, top to bottom, in px. */
  h: number | readonly number[];
  w?: number;
  m?: MantineSpacing;
}

/** A loading placeholder announced as a status (one pattern for every screen). */
export function Loading({ label, h, w, m }: LoadingProps) {
  const heights = typeof h === 'number' ? [h] : h;
  return (
    <Stack role="status" aria-busy="true" aria-label={label} gap="md" {...(m ? { m } : {})}>
      {/* A live region is read by its text, not its label: the label is also written out. */}
      <VisuallyHidden>{label}</VisuallyHidden>
      {heights.map((height, index) => (
        <Skeleton key={index} h={height} {...(w ? { w } : {})} />
      ))}
    </Stack>
  );
}
