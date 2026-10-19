import { LineChart } from '@mantine/charts';
import { Divider, Group, Paper, Stack, Text } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { IconCalendar } from '@tabler/icons-react';

import { Loading } from '@/shared/ui/Loading';
import type { Decimal, IsoDate } from '@/api/contract';
import { addDays, formatDate, formatSignedMoney } from '@/shared/format';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SignedMoney } from '@/shared/ui/SignedMoney';

import { useCumulativePnl } from '../hooks/usePortfolio';
import { type ChartPoint, hasIncompleteDay, incompleteReason, toChartData } from './chartData';

interface CumulativePnlCardProps {
  date: IsoDate;
  /** The cumulative P&L of the selected date, from the same publication as the KPIs. */
  cumulative: Decimal | null;
  /** The chart's first day, before `date` (`useChartStart`). */
  start: IsoDate;
  onStartChange: (start: IsoDate) => void;
}

interface TooltipContentProps {
  active?: boolean;
  payload?: readonly { payload?: unknown }[];
}

/**
 * Tooltip text formatted from the exact decimal string, never from the plotted float, with the
 * reason a day adds nothing when it is not complete (OQ-41 item 5).
 */
export function ChartTooltip({ active, payload }: TooltipContentProps) {
  const point = payload?.[0]?.payload as ChartPoint | undefined;
  if (!active || !point) return null;
  const reason = incompleteReason(point);
  return (
    <Paper p="xs" shadow="sm">
      <Text size="xs" c="dimmed">
        {formatDate(point.date)}
      </Text>
      <SignedMoney value={point.cumulativeText} size="sm" fw={500} />
      {reason !== null && (
        <Text size="xs" c="dimmed">
          {reason}
        </Text>
      )}
    </Paper>
  );
}

/**
 * Compact portfolio-level cumulative P&L (§11.4): one point per calendar day of the period
 * (OQ-41). The user picks where the chart starts; it always ends on the selected date, so the
 * line ends at the headline figure of the same publication.
 */
export function CumulativePnlCard({
  date,
  cumulative,
  start,
  onStartChange,
}: CumulativePnlCardProps) {
  const series = useCumulativePnl(start, date);
  const points = series.data ? toChartData(series.data.items) : [];

  return (
    <Paper p="lg" aria-label="P&L acumulado" role="region">
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Text size="sm" c="dimmed">
            P&L acumulado
          </Text>
          <SignedMoney value={cumulative} size="xl" fw={500} />
        </Stack>
        <Stack gap={4} align="flex-end">
          <DatePickerInput
            label="Início do gráfico"
            size="xs"
            value={start}
            onChange={(value) => {
              if (value) onStartChange(value);
            }}
            maxDate={addDays(date, -1)}
            valueFormat="DD/MM/YYYY"
            leftSection={<IconCalendar size={14} stroke={1.5} />}
            w={160}
          />
          <Text size="sm" c="dimmed">
            Até {formatDate(date)}
          </Text>
        </Stack>
      </Group>
      <Divider my="md" />
      {series.isPending && <Loading label="Carregando P&L acumulado" h={180} />}
      {series.isError && (
        <ErrorState
          error={series.error}
          onRetry={() => void series.refetch()}
          title="Não foi possível carregar o histórico"
        />
      )}
      {series.isSuccess &&
        (points.length > 0 ? (
          <LineChart
            h={180}
            data={points}
            dataKey="label"
            series={[{ name: 'cumulative', label: 'P&L acumulado', color: 'maravi.6' }]}
            curveType="linear"
            withLegend={false}
            gridAxis="y"
            valueFormatter={(value) => formatSignedMoney(String(value))}
            tooltipProps={{ content: ChartTooltip }}
            yAxisProps={{ width: 90 }}
          />
        ) : (
          <Text size="sm" c="dimmed">
            Sem histórico completo para exibir no período selecionado.
          </Text>
        ))}
      <Text size="xs" c="dimmed" mt="xs">
        P&L diário somado desde o início escolhido.
      </Text>
      {series.isSuccess && hasIncompleteDay(points) && (
        <Text size="xs" c="dimmed">
          Há dias incompletos no período (não processados, com erro, em processamento ou sem P&L
          diário): eles somam zero ao acumulado.
        </Text>
      )}
    </Paper>
  );
}
