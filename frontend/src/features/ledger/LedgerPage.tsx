import { Button, Group, Paper, Stack, Text } from '@mantine/core';
import { IconPlayerPlay, IconPlus, IconTrash } from '@tabler/icons-react';
import { useMemo, useState } from 'react';

import { PageTitle } from '@/shared/ui/PageTitle';
import { PeriodPicker } from '@/shared/ui/PeriodPicker';
import { SearchInput } from '@/shared/ui/SearchInput';
import { useInstrumentTypes } from '@/shared/queries';
import { Loading } from '@/shared/ui/Loading';
import {
  type ProcessingDraft,
  ProcessingRequestModal,
} from '@/shared/processing/ProcessingRequestModal';
import { countLabel } from '@/shared/format';
import { ErrorState } from '@/shared/ui/ErrorState';
import { LoadMore } from '@/shared/ui/LoadMore';

import { CashStrip } from './components/CashStrip';
import { type DeleteTarget, DeleteDialog } from './components/DeleteDialog';
import { EntriesTable } from './components/EntriesTable';
import { NewEntryModal } from './components/NewEntryModal';
import { toRow } from './model/entries';
import { useEntries, useIsSavingEntry, useLedgerFilters } from './hooks/useLedger';
import { processCashDraft, processDraft } from './processingDraft';

const NO_SELECTION: ReadonlySet<string> = new Set();

/** "encontrados" once every page is read; "exibidos" while the backend has more (P21). */
const entriesLabel = (n: number, more: boolean) =>
  more
    ? countLabel(n, 'lançamento exibido', 'lançamentos exibidos')
    : countLabel(n, 'lançamento encontrado', 'lançamentos encontrados');

/**
 * Lançamentos (spec §11.3): trades and cash movements in an inclusive range, with a search;
 * the cash strip for the range's end; one modal for compra, venda, aporte and retirada; single
 * and multiple delete with confirmation. There is no editing (§6.1).
 */
export function LedgerPage() {
  const filters = useLedgerFilters();
  const { start, end, search, today } = filters;
  const { order: sort } = filters;
  const list = useEntries(start, end, search, sort);
  const instrumentTypes = useInstrumentTypes();
  const saving = useIsSavingEntry();

  const [creating, setCreating] = useState(false);
  const [processing, setProcessing] = useState<ProcessingDraft | null>(null);
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);

  // A selection belongs to one range and search: a new filter starts with nothing selected,
  // so a row hidden by a filter can never come back selected and be deleted unnoticed.
  const scope = `${start}|${end}|${search}`;
  const [selection, setSelection] = useState({ scope, keys: NO_SELECTION });
  if (selection.scope !== scope) setSelection({ scope, keys: NO_SELECTION });
  const selected = selection.scope === scope ? selection.keys : NO_SELECTION;
  const setSelected = (keys: ReadonlySet<string>) => {
    setSelection({ scope, keys });
  };

  // The backend filters and orders the rows (GET /ledger/entries); they are only mapped here.
  const entries = useMemo(() => (list.data ? list.data.items.map(toRow) : []), [list.data]);
  // Only listed entries count: a deleted row leaves the selection with the refetch.
  const visibleSelection = useMemo(
    () => new Set(entries.filter((e) => selected.has(e.id)).map((e) => e.id)),
    [entries, selected],
  );
  const typeNames = useMemo(
    () => new Map((instrumentTypes.data?.items ?? []).map((t) => [t.code, t.name])),
    [instrumentTypes.data],
  );

  const toggle = (key: string) => {
    const next = new Set(visibleSelection);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelected(next);
  };
  const toggleAll = () => {
    setSelected(
      visibleSelection.size === entries.length ? NO_SELECTION : new Set(entries.map((e) => e.id)),
    );
  };

  return (
    <Stack gap="md">
      <PageTitle>Lançamentos</PageTitle>
      <Group justify="space-between" align="flex-end" wrap="wrap">
        <Group align="flex-end" gap="sm" wrap="wrap">
          <PeriodPicker
            start={start}
            end={end}
            maxDate={today}
            allowSingleDateInRange
            w={260}
            onChange={({ start: nextStart, end: nextEnd }) => {
              filters.setRange(nextStart, nextEnd);
            }}
          />
          <SearchInput
            label="Buscar"
            placeholder="Buscar ativo ou lançamento..."
            w={300}
            value={search}
            onChange={filters.setSearch}
          />
        </Group>
        <Group gap="sm">
          {visibleSelection.size > 0 && (
            <Button
              variant="light"
              color="red"
              leftSection={<IconTrash size={16} stroke={1.5} />}
              onClick={() => {
                setDeleting({
                  mode: 'many',
                  entries: entries.filter((e) => visibleSelection.has(e.id)),
                });
              }}
            >
              Excluir selecionados
            </Button>
          )}
          <Button
            variant="default"
            leftSection={<IconPlayerPlay size={16} stroke={1.5} />}
            onClick={() => {
              setProcessing(processDraft(start, end));
            }}
          >
            Processar
          </Button>
          <Button
            leftSection={<IconPlus size={16} stroke={1.5} />}
            onClick={() => {
              setCreating(true);
            }}
          >
            Novo lançamento
          </Button>
        </Group>
      </Group>

      <CashStrip
        end={end}
        onProcessCash={(from) => {
          setProcessing(processCashDraft(from, end));
        }}
      />

      {list.isError ? (
        <ErrorState
          error={list.error}
          onRetry={() => {
            void list.refetch();
          }}
        />
      ) : list.isPending ? (
        <Loading label="Carregando lançamentos" h={320} />
      ) : (
        <Paper>
          <EntriesTable
            entries={entries}
            instrumentTypeNames={typeNames}
            sort={sort}
            onToggleSort={() => {
              filters.setOrder(sort === 'desc' ? 'asc' : 'desc');
            }}
            selected={visibleSelection}
            onToggle={toggle}
            onToggleAll={toggleAll}
            onDelete={(entry) => {
              setDeleting({ mode: 'one', entry });
            }}
          />
          {entries.length === 0 && (
            <Text size="sm" c="dimmed" ta="center" py="xl">
              Nenhum lançamento no período.
            </Text>
          )}
          <LoadMore
            hasMore={list.hasNextPage}
            loading={list.isFetchingNextPage}
            onLoad={() => {
              void list.fetchNextPage();
            }}
          />
          <Text size="sm" c="dimmed" p="md" role="status">
            {entriesLabel(entries.length, list.hasNextPage)}
          </Text>
        </Paper>
      )}

      {/* While a save runs the modal stays open: its result (notification or errors) belongs
          to the form, which closing would unmount. */}
      <NewEntryModal
        opened={creating}
        onClose={() => {
          setCreating(false);
        }}
        today={today}
        saving={saving}
      />

      <ProcessingRequestModal
        draft={processing}
        onClose={() => {
          setProcessing(null);
        }}
        today={today}
        queuedMessage="Processamento colocado na fila. Acompanhe em Central de Controle."
      />

      <DeleteDialog
        target={deleting}
        onClose={() => {
          setDeleting(null);
        }}
        onRetarget={setDeleting}
        refreshListed={async () => {
          const result = await list.refetch();
          return new Set((result.data?.items ?? []).map((item) => item.id));
        }}
      />
    </Stack>
  );
}
