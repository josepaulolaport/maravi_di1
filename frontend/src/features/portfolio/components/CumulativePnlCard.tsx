import { LineChart } from '@mantine/charts';
import { Divider, Group, Paper, Skeleton, Stack, Text } from '@mantine/core';

import type { Decimal, IsoDate } from '@/api/contract';
import { formatDate, formatSignedMoney } from '@/shared/format';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SignedMoney } from '@/shared/ui/SignedMoney';

import { useCumulativePnl } from '../hooks/usePortfolio';
import { type ChartPoint, hasHistory, toChartData } from './chartData';

interface CumulativePnlCardProps {
  date: IsoDate;
  /** The cumulative P&L of the selected date, from the same publication as the KPIs. */
  cumulative: Decimal | null;
}

interface TooltipContentProps {
  active?: boolean;
  payload?: readonly { payload?: unknown }[];
}

/** Tooltip text formatted from the exact decimal string, never from the plotted float. */
function ChartTooltip({ active, payload }: TooltipContentProps) {
  const point = payload?.[0]?.payload as ChartPoint | undefined;
  if (!active || !point || point.cumulativeText === null) return null;
  return (
    <Paper p="xs" shadow="sm">
      <Text size="xs" c="dimmed">
        {formatDate(point.date)}
      </Text>
      <SignedMoney value={point.cumulativeText} size="sm" fw={500} />
    </Paper>
  );
}

/** Compact portfolio-level cumulative P&L, drawn only where the history is complete (§11.4). */
export function CumulativePnlCard({ date, cumulative }: CumulativePnlCardProps) {
  const series = useCumulativePnl(date);
  const points = series.data ? toChartData(series.data.items, series.start, date) : [];

  return (
    <Paper p="lg" aria-label="P&L acumulado" role="region">
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Text size="sm" c="dimmed">
            P&L acumulado
          </Text>
          <SignedMoney value={cumulative} size="xl" fw={500} />
        </Stack>
        <Text size="sm" c="dimmed">
          Até {formatDate(date)}
        </Text>
      </Group>
      <Divider my="md" />
      {series.isPending && <Skeleton h={180} />}
      {series.isError && (
        <ErrorState
          error={series.error}
          onRetry={() => void series.refetch()}
          title="Não foi possível carregar o histórico"
        />
      )}
      {series.isSuccess &&
        (hasHistory(points) ? (
          <LineChart
            h={180}
            data={points}
            dataKey="label"
            series={[{ name: 'cumulative', label: 'P&L acumulado', color: 'maravi.6' }]}
            curveType="linear"
            connectNulls={false}
            withLegend={false}
            gridAxis="y"
            valueFormatter={(value) => formatSignedMoney(String(value))}
            tooltipProps={{ content: ChartTooltip }}
            yAxisProps={{ width: 90 }}
          />
        ) : (
          <Text size="sm" c="dimmed">
            Sem histórico completo para exibir nos últimos 30 dias.
          </Text>
        ))}
      <Text size="xs" c="dimmed" mt="xs">
        Somente dias processados com P&L completo e atual. Lacunas indicam dias sem resultado
        válido.
      </Text>
    </Paper>
  );
}
