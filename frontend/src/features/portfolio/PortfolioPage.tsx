import { Group, Skeleton, Stack } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { IconCalendar } from '@tabler/icons-react';

import type { IsoDate } from '@/api/contract';
import { ErrorState } from '@/shared/ui/ErrorState';

import { CumulativePnlCard } from './components/CumulativePnlCard';
import { DataStatus } from './components/DataStatus';
import { KpiGrid } from './components/KpiGrid';
import { PositionsTable } from './components/PositionsTable';
import { NotProcessedNotice } from './components/StatusNotices';
import {
  useEvaluationDate,
  usePortfolioPositions,
  usePortfolioSummary,
} from './hooks/usePortfolio';

/**
 * Carteira (spec §11.4): one evaluation date, published data only; nothing is recalculated
 * here. Cash and positions are published by separate chains (OQ-21 draft), so each KPI and
 * notice follows its own chain's freshness; AUM joins both.
 */
export function PortfolioPage() {
  const [date, setDate, today] = useEvaluationDate();
  const summary = usePortfolioSummary(date);
  const positions = usePortfolioPositions(date);

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end">
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
        {summary.data && <DataStatus summary={summary.data} />}
      </Group>
      <PortfolioBody date={date} summary={summary} positions={positions} />
    </Stack>
  );
}

interface BodyProps {
  date: IsoDate;
  summary: ReturnType<typeof usePortfolioSummary>;
  positions: ReturnType<typeof usePortfolioPositions>;
}

function PortfolioBody({ date, summary, positions }: BodyProps) {
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
  const rows = positions.data;
  if (data.cash.status === 'NOT_PROCESSED' && data.positions.status === 'NOT_PROCESSED') {
    return <NotProcessedNotice date={date} />;
  }

  return (
    <Stack gap="md">
      <KpiGrid summary={data} />
      {rows.status !== 'NOT_PROCESSED' && (
        <>
          <CumulativePnlCard date={date} cumulative={data.positions.cumulative_pnl} />
          <PositionsTable rows={rows.items} />
        </>
      )}
    </Stack>
  );
}
