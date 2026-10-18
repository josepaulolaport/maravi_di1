import { Badge, type BadgeProps, type MantineColor } from '@mantine/core';

interface StatusBadgeProps extends Omit<BadgeProps, 'color' | 'children'> {
  /** pt-BR text, always shown: colour is never the only signal. */
  label: string;
  color: MantineColor;
  /**
   * Announce changes to screen readers (`role="status"`). Only for a badge being followed,
   * such as the job in the details drawer; a table of badges stays silent while polling.
   */
  live?: boolean;
}

/** A status (job, publication) as a labelled badge. */
export function StatusBadge({ label, color, live = false, ...props }: StatusBadgeProps) {
  return (
    <Badge
      {...(live ? { role: 'status' } : {})}
      color={color}
      variant="light"
      radius="sm"
      tt="none"
      fw={500}
      {...props}
    >
      {label}
    </Badge>
  );
}
