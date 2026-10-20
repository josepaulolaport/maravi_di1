import { Paper, Text } from '@mantine/core';
import type { ReactNode } from 'react';

import type { IsoDate } from '@/api/contract';
import { formatDate } from '@/shared/format';

/** What recharts passes a tooltip's `content`: the hovered point is the first payload's. */
interface TooltipContentProps<Point> {
  active?: boolean;
  payload?: readonly { payload?: Point | undefined }[];
}

/**
 * A chart's tooltip (recharts `content`): the point's date, then what `body` shows for it, which
 * formats the exact decimal string, never the plotted float. `body` returns `null` for a point
 * with nothing to show. Built once per chart, outside render.
 */
export function chartTooltip<Point extends { date: IsoDate }>(
  body: (point: Point) => ReactNode,
): (props: TooltipContentProps<Point>) => ReactNode {
  return function ChartTooltip({ active, payload }) {
    const point = payload?.[0]?.payload;
    if (!active || !point) return null;
    const content = body(point);
    if (content === null) return null;
    return (
      <Paper p="xs" shadow="sm">
        <Text size="xs" c="dimmed">
          {formatDate(point.date)}
        </Text>
        {content}
      </Paper>
    );
  };
}
