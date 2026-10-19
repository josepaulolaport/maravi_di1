import {
  ActionIcon,
  Menu,
  Paper,
  Skeleton,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  VisuallyHidden,
} from '@mantine/core';
import { IconDots, IconSearch } from '@tabler/icons-react';

import type { ProcessingRequest } from '@/api/contract';
import { formatQuantity } from '@/shared/format';
import { ErrorState } from '@/shared/ui/ErrorState';
import { StatusBadge } from '@/shared/ui/StatusBadge';

import { formatPeriod, formatProgress, shortId } from '../format';
import type { useProcessingRequests } from '../hooks/useProcessing';
import { canCancel, canRequestAgain, jobStatusBadge } from '../jobStatus';

/** What the user can do with a job, from its row menu or its details drawer (OQ-20). */
export interface JobActions {
  onDetails: (job: ProcessingRequest) => void;
  onCancel: (job: ProcessingRequest) => void;
  onReplace: (job: ProcessingRequest) => void;
  onRequestAgain: (job: ProcessingRequest) => void;
}

function matchesSearch(job: ProcessingRequest, search: string): boolean {
  const needle = search.trim().toLocaleLowerCase('pt-BR');
  if (!needle) return true;
  return [
    shortId(job.id),
    formatPeriod(job.requested_start_date, job.requested_end_date),
    jobStatusBadge(job.status).label,
  ].some((value) => value.toLocaleLowerCase('pt-BR').includes(needle));
}

const countLabel = (n: number) =>
  n === 1 ? '1 processamento encontrado' : `${formatQuantity(n)} processamentos encontrados`;

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
        <TextInput
          aria-label="Buscar processamento"
          placeholder="Buscar processamento..."
          leftSection={<IconSearch size={16} stroke={1.5} />}
          value={search}
          onChange={(event) => {
            onSearchChange(event.currentTarget.value);
          }}
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
    return <Skeleton h={220} aria-busy="true" aria-label="Carregando processamentos" />;
  }
  const rows = requests.data.items.filter((job) => matchesSearch(job, search));
  return (
    <>
      <Table.ScrollContainer minWidth={640}>
        <Table verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Processamento</Table.Th>
              <Table.Th>Período</Table.Th>
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
                <Table.Td colSpan={5}>
                  <Text size="sm" c="dimmed" ta="center" py="md">
                    Nenhum processamento encontrado.
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              rows.map((job) => <JobRow key={job.id} job={job} actions={actions} />)
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Text size="sm" c="dimmed">
        {countLabel(rows.length)}
      </Text>
    </>
  );
}

function JobRow({ job, actions }: { job: ProcessingRequest; actions: JobActions }) {
  const badge = jobStatusBadge(job.status);
  const id = shortId(job.id);
  return (
    <Table.Tr>
      <Table.Td ff="monospace">{id}</Table.Td>
      <Table.Td>{formatPeriod(job.requested_start_date, job.requested_end_date)}</Table.Td>
      <Table.Td>{formatProgress(job.processed_days, job.total_days)}</Table.Td>
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
            {canCancel(job.status) && (
              <>
                <Menu.Item
                  color="red"
                  onClick={() => {
                    actions.onCancel(job);
                  }}
                >
                  Cancelar processamento
                </Menu.Item>
                <Menu.Item
                  onClick={() => {
                    actions.onReplace(job);
                  }}
                >
                  Cancelar e criar novo processamento
                </Menu.Item>
              </>
            )}
            {canRequestAgain(job.status) && (
              <Menu.Item
                onClick={() => {
                  actions.onRequestAgain(job);
                }}
              >
                Solicitar novo processamento
              </Menu.Item>
            )}
          </Menu.Dropdown>
        </Menu>
      </Table.Td>
    </Table.Tr>
  );
}
