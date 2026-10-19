import { Group, Skeleton, Stack } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { IconCalendar } from '@tabler/icons-react';

import type { IsoDate } from '@/api/contract';
import { ErrorState } from '@/shared/ui/ErrorState';

import { CumulativePnlCard } from './components/CumulativePnlCard';
import { KpiGrid } from './components/KpiGrid';
import { PositionsTable } from './components/PositionsTable';
import { NotProcessedNotice, PublishedNotices } from './components/StatusNotices';
import {
  useChartStart,
  useEvaluationDate,
  usePortfolioPositions,
  usePortfolioSummary,
} from './hooks/usePortfolio';

/**
 * Carteira (spec §11.4): one evaluation date, published data only. KPIs, positions and the
 * cumulative P&L headline come from the same publication; nothing is recalculated here.
 */
export function PortfolioPage() {
  const [date, setDate, today] = useEvaluationDate();
  // Read here, not in the chart card, so a start the date has passed is dropped from the URL
  // even on a date whose card is not shown (not processed).
  const chartStart = useChartStart(date);
  const summary = usePortfolioSummary(date);
  const positions = usePortfolioPositions(date);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <DatePickerInput
          label="Data de avaliação"
          value={date}
          onChange={(value) => {
            if (value) setDate(value);
          }}
          maxDate={today}
          valueFormat="DD/MM/YYYY"
          leftSection={<IconCalendar size={16} stroke={1.5} />}
          w={220}
        />
      </Group>
      <PortfolioBody chartStart={chartStart} date={date} summary={summary} positions={positions} />
    </Stack>
  );
}

interface BodyProps {
  date: IsoDate;
  chartStart: ReturnType<typeof useChartStart>;
  summary: ReturnType<typeof usePortfolioSummary>;
  positions: ReturnType<typeof usePortfolioPositions>;
}

function PortfolioBody({ date, chartStart, summary, positions }: BodyProps) {
  if (summary.isError || positions.isError) {
    return (
      <ErrorState
        error={summary.error ?? positions.error}
        onRetry={() => {
          void summary.refetch();
          void positions.refetch();
        }}
      />
    );
  }
  if (summary.isPending || positions.isPending) {
    return (
      <Stack gap="md" aria-busy="true" aria-label="Carregando carteira">
        <Skeleton h={76} />
        <Skeleton h={260} />
        <Skeleton h={220} />
      </Stack>
    );
  }

  const data = summary.data;
  if (data.publication === 'NOT_PROCESSED' || positions.data.publication === 'NOT_PROCESSED') {
    return <NotProcessedNotice date={date} />;
  }

  return (
    <Stack gap="md">
      <PublishedNotices
        date={date}
        stale={data.stale || positions.data.stale}
        incomplete={data.valuation_status === 'MISSING' || data.pnl_status === 'MISSING'}
      />
      <KpiGrid kpis={data} />
      <CumulativePnlCard
        date={date}
        cumulative={data.cumulative_pnl}
        start={chartStart[0]}
        onStartChange={chartStart[1]}
      />
      <PositionsTable rows={positions.data.items} />
    </Stack>
  );
}
