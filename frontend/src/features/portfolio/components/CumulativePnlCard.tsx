import { LineChart } from '@mantine/charts';
import { Divider, Group, Paper, Skeleton, Stack, Text } from '@mantine/core';

import type { IsoDate } from '@/api/contract';
import { addDays, formatDate, formatSignedMoney } from '@/shared/format';
import { DateField } from '@/shared/ui/DateField';
import { ErrorState } from '@/shared/ui/ErrorState';
import { Loading } from '@/shared/ui/Loading';
import { SignedMoney } from '@/shared/ui/SignedMoney';

import { useCumulativePnl } from '../hooks/usePortfolio';
import { hasIncompleteDay, toChartData } from '../model/chartData';
import { PnlTooltip } from './PnlTooltip';

interface CumulativePnlCardProps {
  date: IsoDate;
  /** The chart's first day, before `date` (`useChartStart`). */
  start: IsoDate;
  onStartChange: (start: IsoDate) => void;
}

/**
 * Compact portfolio-level cumulative P&L (§11.4): one point per calendar day of the period
 * (OQ-41). The user picks where the chart starts; it always ends on the selected date. The
 * headline is the chart's range total on that date, "Desde" its start (OQ-48 item 3): the
 * backend's `range_cumulative_pnl`, where an incomplete day adds 0. The stored since-inception
 * `cumulative_pnl` stays unavailable from the first gap (§8.3) and is not shown here.
 */
export function CumulativePnlCard({ date, start, onStartChange }: CumulativePnlCardProps) {
  const series = useCumulativePnl(start, date);
  const points = series.data ? toChartData(series.data.items) : [];
  const total = points.find((point) => point.date === date)?.cumulativeText ?? null;

  return (
    <Paper p="lg" aria-label="P&L acumulado" role="region">
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Text size="sm" c="dimmed">
            P&L acumulado
          </Text>
          {/* While the series is read the total is not known yet: loading, never "—". */}
          {series.isPending ? (
            <Skeleton h={31} w={160} aria-busy="true" aria-label="Carregando total do período" />
          ) : (
            <SignedMoney value={total} size="xl" fw={500} />
          )}
          <Text size="sm" c="dimmed">
            Desde {formatDate(start)}
          </Text>
        </Stack>
        <Stack gap={4} align="flex-end">
          <DateField
            label="Início do gráfico"
            size="xs"
            value={start}
            onChange={(value) => {
              if (value) onStartChange(value);
            }}
            maxDate={addDays(date, -1)}
            limitMessage="O início do gráfico deve ser anterior à data de avaliação."
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
            tooltipProps={{ content: PnlTooltip }}
            yAxisProps={{ width: 90 }}
          />
        ) : (
          <Text size="sm" c="dimmed">
            Sem dados para o período selecionado.
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
