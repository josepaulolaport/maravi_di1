import { Group, Stack } from '@mantine/core';
import type { UseQueryResult } from '@tanstack/react-query';

import { PageTitle } from '@/shared/ui/PageTitle';
import { useSummary } from '@/shared/queries';
import { Loading } from '@/shared/ui/Loading';
import type { PortfolioPositions, PortfolioSummary } from '@/api/contract';
import { DateField } from '@/shared/ui/DateField';
import { ErrorState } from '@/shared/ui/ErrorState';

import { CumulativePnlCard } from './components/CumulativePnlCard';
import { DataStatus } from './components/DataStatus';
import { KpiGrid } from './components/KpiGrid';
import { PositionsTable } from './components/PositionsTable';
import { NotProcessedNotice } from './components/StatusNotices';
import {
  type PortfolioParams,
  usePortfolioParams,
  usePortfolioPositions,
} from './hooks/usePortfolio';

/**
 * Carteira (spec §11.4): one evaluation date, published data only; nothing is recalculated
 * here. Cash and positions are published by separate chains (OQ-21), so each KPI and
 * notice follows its own chain's status (OQ-31); AUM joins both.
 */
export function PortfolioPage() {
  const view = usePortfolioParams();
  const { date, setDate, today } = view;
  const summary = useSummary(date);
  const positions = usePortfolioPositions(date);

  return (
    <Stack gap="md">
      <PageTitle>Carteira</PageTitle>
      <Group justify="space-between" align="flex-end">
        <DateField
          label="Data de avaliação"
          value={date}
          onChange={(value) => {
            if (value) setDate(value);
          }}
          maxDate={today}
          w={220}
        />
        {summary.data && <DataStatus summary={summary.data} />}
      </Group>
      <PortfolioBody view={view} summary={summary} positions={positions} />
    </Stack>
  );
}

interface BodyProps {
  view: PortfolioParams;
  summary: UseQueryResult<PortfolioSummary>;
  positions: UseQueryResult<PortfolioPositions>;
}

function PortfolioBody({ view, summary, positions }: BodyProps) {
  const { date } = view;
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
    return <Loading label="Carregando carteira" h={[76, 260, 220]} />;
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
          <CumulativePnlCard
            date={date}
            start={view.chartStart}
            onStartChange={view.setChartStart}
          />
          <PositionsTable rows={rows.items} view={view} />
        </>
      )}
    </Stack>
  );
}
