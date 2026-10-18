import { LineChart } from '@mantine/charts';
import { Group, Paper, SegmentedControl, Text, Title } from '@mantine/core';
import { useState } from 'react';

import type { IsoDate, ReferencePriceDay } from '@/api/contract';
import { formatDate, formatPu, formatRate } from '@/shared/format';

import { type ChartMode, type PricePoint, toPriceChart } from './calendarData';

interface PriceHistoryCardProps {
  items: ReferencePriceDay[];
  start: IsoDate;
  end: IsoDate;
}

const formatters: Record<ChartMode, (value: string) => string> = {
  PU: formatPu,
  RATE: formatRate,
};

interface TooltipContentProps {
  active?: boolean;
  payload?: readonly { payload?: unknown }[];
}

/** Tooltip text is formatted from the exact decimal string, never from the plotted float. */
function tooltipFor(format: (value: string) => string) {
  return function ChartTooltip({ active, payload }: TooltipContentProps) {
    const point = payload?.[0]?.payload as PricePoint | undefined;
    if (!active || !point || point.text === null) return null;
    return (
      <Paper p="xs" shadow="sm">
        <Text size="xs" c="dimmed">
          {formatDate(point.date)}
        </Text>
        <Text size="sm" fw={500}>
          {format(point.text)}
        </Text>
      </Paper>
    );
  };
}

const tooltips: Record<ChartMode, ReturnType<typeof tooltipFor>> = {
  PU: tooltipFor(formatPu),
  RATE: tooltipFor(formatRate),
};

/** "Histórico de preços" (§11.2): the preferred observation of each day, PU or rate. */
export function PriceHistoryCard({ items, start, end }: PriceHistoryCardProps) {
  const [mode, setMode] = useState<ChartMode>('PU');
  const points = toPriceChart(items, start, end, mode);
  const format = formatters[mode];

  return (
    <Paper p="lg" role="region" aria-label="Histórico de preços">
      <Group justify="space-between" mb="md">
        <Title order={2} size="h5" fw={500}>
          Histórico de preços
        </Title>
        <SegmentedControl
          size="xs"
          aria-label="Valor do gráfico"
          value={mode}
          onChange={(value) => {
            setMode(value);
          }}
          data={[
            { value: 'PU', label: 'PU' },
            { value: 'RATE', label: 'Taxa a.a.' },
          ]}
        />
      </Group>
      {points.some((p) => p.value !== null) ? (
        <LineChart
          h={180}
          data={points}
          dataKey="label"
          series={[{ name: 'value', label: mode === 'PU' ? 'PU' : 'Taxa a.a.', color: 'maravi.6' }]}
          curveType="linear"
          connectNulls={false}
          withLegend={false}
          gridAxis="y"
          valueFormatter={(value) => format(String(value))}
          tooltipProps={{ content: tooltips[mode] }}
          yAxisProps={{ width: 90, domain: ['auto', 'auto'] }}
        />
      ) : (
        <Text size="sm" c="dimmed">
          Nenhuma referência registrada neste período.
        </Text>
      )}
      <Text size="xs" c="dimmed" mt="xs">
        Somente referências registradas. Lacunas indicam ausência de observação, não erro de
        precificação.
      </Text>
    </Paper>
  );
}
