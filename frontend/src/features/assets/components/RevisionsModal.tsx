import { Modal, Skeleton, Table } from '@mantine/core';

import type { IsoDate } from '@/api/contract';
import { formatDate, formatDateTime, formatPu, formatRate } from '@/shared/format';
import { ErrorState } from '@/shared/ui/ErrorState';

import { useRevisions } from '../hooks/usePrices';
import { SOURCE_LABELS } from './PriceCalendar';

interface RevisionsModalProps {
  assetId: string;
  /** The date whose revisions are shown; `null` closes the modal. */
  date: IsoDate | null;
  onClose: () => void;
}

/**
 * "Ver revisões" (§5): every revision of both sources for one date, newest first, with when it
 * was recorded and when it was superseded. History is never edited, only appended.
 */
export function RevisionsModal({ assetId, date, onClose }: RevisionsModalProps) {
  const revisions = useRevisions(assetId, date);
  return (
    <Modal
      opened={date !== null}
      onClose={onClose}
      title={date ? `Revisões de ${formatDate(date)}` : ''}
      size="xl"
      centered
      closeButtonProps={{ 'aria-label': 'Fechar' }}
    >
      {revisions.isError ? (
        <ErrorState error={revisions.error} onRetry={() => void revisions.refetch()} />
      ) : revisions.isPending ? (
        <Skeleton h={120} role="status" aria-label="Carregando revisões" />
      ) : (
        <Table.ScrollContainer minWidth={600}>
          <Table aria-label="Revisões" verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Fonte</Table.Th>
                <Table.Th ta="right">Revisão</Table.Th>
                <Table.Th ta="right">PU</Table.Th>
                <Table.Th ta="right">Taxa a.a.</Table.Th>
                <Table.Th>Registrada em</Table.Th>
                <Table.Th>Substituída em</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {revisions.data.items.map((revision) => (
                <Table.Tr key={revision.id}>
                  <Table.Td>{SOURCE_LABELS[revision.source]}</Table.Td>
                  <Table.Td ta="right">{revision.revision}</Table.Td>
                  <Table.Td ta="right">{formatPu(revision.pu)}</Table.Td>
                  <Table.Td ta="right">{formatRate(revision.rate)}</Table.Td>
                  <Table.Td>{formatDateTime(revision.created_at)}</Table.Td>
                  <Table.Td>
                    {revision.superseded_at ? formatDateTime(revision.superseded_at) : 'Atual'}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Modal>
  );
}
