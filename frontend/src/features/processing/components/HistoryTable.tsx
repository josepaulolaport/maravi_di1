import { ActionIcon, Menu, Paper, Stack, Table, Text, Title, VisuallyHidden } from '@mantine/core';
import { IconDots } from '@tabler/icons-react';

import { SearchInput } from '@/shared/ui/SearchInput';
import { Loading } from '@/shared/ui/Loading';
import type { ProcessingRequest } from '@/api/contract';
import { countLabel } from '@/shared/format';
import { ErrorState } from '@/shared/ui/ErrorState';
import { LoadMore } from '@/shared/ui/LoadMore';
import { StatusBadge } from '@/shared/ui/StatusBadge';

import { SCOPE_LABELS } from '@/shared/processing/scope';

import { formatPeriod, formatProgress, shortId } from '../model/format';
import type { useProcessingRequests } from '../hooks/useProcessing';
import { canCancel, runBadge, progressOf, retryRequests } from '../model/jobStatus';
import type { RetryRequest } from '../model/jobStatus';

/**
 * What the user can do with a job, from its row menu or its details modal (OQ-20). Cancel and
 * queue are separate actions: there is no cancel and replace (OQ-30). A new request prefills
 * one of the run's `retryRequests` (OQ-23, OQ-40).
 */
export interface JobActions {
  onDetails: (job: ProcessingRequest) => void;
  onCancel: (job: ProcessingRequest) => void;
  onRequestAgain: (retry: RetryRequest) => void;
}

function matchesSearch(job: ProcessingRequest, search: string): boolean {
  const needle = search.trim().toLocaleLowerCase('pt-BR');
  if (!needle) return true;
  return [
    shortId(job.id),
    formatPeriod(job.start_date, job.end_date),
    SCOPE_LABELS[job.scope],
    runBadge(job).label,
  ].some((value) => value.toLocaleLowerCase('pt-BR').includes(needle));
}

/** "encontrados" once every page is read; "exibidos" while the backend has more (P21). */
const jobsLabel = (n: number, more: boolean) =>
  more
    ? countLabel(n, 'processamento exibido', 'processamentos exibidos')
    : countLabel(n, 'processamento encontrado', 'processamentos encontrados');

interface HistoryTableProps extends JobActions {
  requests: ReturnType<typeof useProcessingRequests>;
  search: string;
  onSearchChange: (text: string) => void;
}

/** "Histórico de processamentos" (§11.1): every job, finished and cancelled ones included. */
export function HistoryTable({ requests, search, onSearchChange, ...actions }: HistoryTableProps) {
  return (
    <Paper p="md" component="section" aria-labelledby="history-title">
      <Stack gap="md">
        <Title order={2} size="h4" id="history-title">
          Histórico de processamentos
        </Title>
        <SearchInput
          label="Buscar processamento"
          placeholder="Buscar processamento..."
          value={search}
          onChange={onSearchChange}
          maw={360}
        />
        <HistoryBody requests={requests} search={search} actions={actions} />
      </Stack>
    </Paper>
  );
}

interface HistoryBodyProps {
  requests: ReturnType<typeof useProcessingRequests>;
  search: string;
  actions: JobActions;
}

function HistoryBody({ requests, search, actions }: HistoryBodyProps) {
  if (requests.isError) {
    return <ErrorState error={requests.error} onRetry={() => void requests.refetch()} />;
  }
  if (requests.isPending) {
    return <Loading label="Carregando processamentos" h={220} />;
  }
  // The search filters the pages read so far; "Carregar mais" reads older jobs.
  const rows = requests.data.items.filter((job) => matchesSearch(job, search));
  return (
    <>
      <Table.ScrollContainer minWidth={640}>
        <Table verticalSpacing="sm" aria-label="Processamentos">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Processamento</Table.Th>
              <Table.Th>Período</Table.Th>
              <Table.Th>Escopo</Table.Th>
              <Table.Th>Progresso</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>
                <VisuallyHidden>Ações</VisuallyHidden>
              </Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text size="sm" c="dimmed" ta="center" py="md">
                    {/* The search covers the pages read so far; older ones may still match. */}
                    {requests.hasNextPage && search.trim()
                      ? 'Nenhum processamento entre os exibidos. Use “Carregar mais” para buscar nos anteriores.'
                      : 'Nenhum processamento encontrado.'}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              rows.map((job) => <JobRow key={job.id} job={job} actions={actions} />)
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <LoadMore
        hasMore={requests.hasNextPage}
        loading={requests.isFetchingNextPage}
        onLoad={() => {
          void requests.fetchNextPage();
        }}
      />
      <Text size="sm" c="dimmed">
        {jobsLabel(rows.length, requests.hasNextPage)}
      </Text>
    </>
  );
}

function JobRow({ job, actions }: { job: ProcessingRequest; actions: JobActions }) {
  const badge = runBadge(job);
  const id = shortId(job.id);
  return (
    <Table.Tr>
      <Table.Td ff="monospace">{id}</Table.Td>
      <Table.Td>{formatPeriod(job.start_date, job.end_date)}</Table.Td>
      <Table.Td>{SCOPE_LABELS[job.scope]}</Table.Td>
      <Table.Td>{formatProgress(progressOf(job).done, progressOf(job).total)}</Table.Td>
      <Table.Td>
        <StatusBadge label={badge.label} color={badge.color} />
      </Table.Td>
      <Table.Td ta="right">
        <Menu position="bottom-end" withinPortal>
          <Menu.Target>
            <ActionIcon variant="subtle" color="gray" aria-label={`Ações do processamento ${id}`}>
              <IconDots size={16} stroke={1.5} />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item
              onClick={() => {
                actions.onDetails(job);
              }}
            >
              Ver detalhes
            </Menu.Item>
            {canCancel(job) && (
              <Menu.Item
                color="red"
                onClick={() => {
                  actions.onCancel(job);
                }}
              >
                Cancelar processamento
              </Menu.Item>
            )}
            {retryRequests(job).map((retry) => (
              <Menu.Item
                key={retry.label}
                onClick={() => {
                  actions.onRequestAgain(retry);
                }}
              >
                {retry.label}
              </Menu.Item>
            ))}
          </Menu.Dropdown>
        </Menu>
      </Table.Td>
    </Table.Tr>
  );
}
