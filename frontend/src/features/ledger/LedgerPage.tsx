import { Button, Group, List, Paper, Stack, Text } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { notifications } from '@mantine/notifications';
import { IconCalendar, IconPlayerPlay, IconPlus, IconTrash } from '@tabler/icons-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { PageTitle } from '@/shared/ui/PageTitle';
import { SearchInput } from '@/shared/ui/SearchInput';
import { useInstrumentTypes } from '@/shared/queries';
import { Loading } from '@/shared/ui/Loading';
import type { IsoDate } from '@/api/contract';
import {
  type ProcessingDraft,
  ProcessingRequestModal,
} from '@/shared/processing/ProcessingRequestModal';
import { countLabel } from '@/shared/format';
import { ConfirmModal } from '@/shared/ui/ConfirmModal';
import { ErrorState } from '@/shared/ui/ErrorState';
import { ApiError } from '@/api/http';
import { problemMessages } from '@/shared/ui/problemMessages';
import { LoadMore } from '@/shared/ui/LoadMore';

import { CashStrip } from './components/CashStrip';
import { EntriesTable, entryLabel } from './components/EntriesTable';
import { NewEntryModal } from './components/NewEntryModal';
import { type LedgerEntry, toRow } from './entries';
import {
  useDeleteEntries,
  useEntries,
  useIsSavingEntry,
  useLedgerFilters,
} from './hooks/useLedger';
import { processCashDraft, processDraft } from './processingDraft';

type DeleteTarget = { mode: 'one'; entry: LedgerEntry } | { mode: 'many'; entries: LedgerEntry[] };

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
          <RangePicker
            key={`${start}:${end}`}
            start={start}
            end={end}
            today={today}
            onChange={(nextStart, nextEnd) => {
              filters.setRange(nextStart, nextEnd);
            }}
          />
          <SearchInput
            label="Buscar"
            placeholder="Buscar ativo ou lançamento..."
            w={300}
            value={search}
            onChange={(next) => {
              filters.setSearch(next);
            }}
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

function RangePicker({
  start,
  end,
  today,
  onChange,
}: {
  start: IsoDate;
  end: IsoDate;
  today: IsoDate;
  onChange: (start: IsoDate, end: IsoDate) => void;
}) {
  // A range being picked (only its first date chosen) stays local until it is complete. The
  // parent remounts this picker (`key`) whenever the URL range changes.
  const [draft, setDraft] = useState<[IsoDate | null, IsoDate | null]>([start, end]);
  return (
    <DatePickerInput
      type="range"
      label="Período"
      value={draft}
      onChange={(value) => {
        setDraft(value);
        const [nextStart, nextEnd] = value;
        if (nextStart && nextEnd) onChange(nextStart, nextEnd);
      }}
      allowSingleDateInRange
      maxDate={today}
      valueFormat="DD/MM/YYYY"
      leftSection={<IconCalendar size={16} stroke={1.5} />}
      w={260}
    />
  );
}

/** Ids of the entries the list shows once it is read again. */
type RefreshListed = () => Promise<ReadonlySet<string>>;

/**
 * Deletes one entry or the selected ones, after confirmation (§6.1). A 404 means an entry is
 * already gone (deleted elsewhere) and nothing was deleted (OQ-32): the list is read again and
 * the dialog keeps only the entries still listed, so "Excluir" can be retried; when none is
 * left, it closes and says so.
 */
function DeleteDialog({
  target,
  onClose,
  onRetarget,
  refreshListed,
}: {
  target: DeleteTarget | null;
  onClose: () => void;
  onRetarget: (target: DeleteTarget) => void;
  refreshListed: RefreshListed;
}) {
  // One request for one entry or many, of either type (`POST /ledger/entries/deletions`).
  const mutation = useDeleteEntries();
  // The last target stays on screen while the dialog closes, so its text does not flicker.
  const [shown, setShown] = useState(target);
  if (target !== null && target !== shown) setShown(target);

  const close = () => {
    mutation.reset();
    onClose();
  };

  // A 404 is followed by a new read of the list; meanwhile "Excluir" waits, and a dialog closed
  // or changed in that time is left alone.
  const [refreshing, setRefreshing] = useState(false);
  const current = useRef(target);
  useEffect(() => {
    current.current = target;
  }, [target]);

  const confirm = () => {
    if (!target || refreshing) return;
    const entries = target.mode === 'one' ? [target.entry] : target.entries;
    mutation.mutate(entries, {
      onSuccess: () => {
        const n = entries.length;
        notifications.show({
          color: 'teal',
          message: n === 1 ? 'Lançamento excluído.' : `${String(n)} lançamentos excluídos.`,
        });
        close();
      },
      onError: (error) => {
        if (error instanceof ApiError && error.status === 404) {
          void dropVanished(target, problemMessages(error).join(' '));
        }
      },
    });
  };

  const dropVanished = async (stale: DeleteTarget, message: string) => {
    setRefreshing(true);
    const listed = await refreshListed().finally(() => {
      setRefreshing(false);
    });
    if (current.current !== stale) return;
    const entries = stale.mode === 'one' ? [stale.entry] : stale.entries;
    const left = entries.filter((e) => listed.has(e.id));
    if (left.length === entries.length) return;
    if (left.length === 0) {
      notifications.show({
        color: 'red',
        message:
          entries.length === 1
            ? `${message} Ele já havia sido excluído; a lista foi atualizada.`
            : `${message} Eles já haviam sido excluídos; a lista foi atualizada.`,
      });
      close();
      return;
    }
    // The 404 does not name the missing entry: the ones no longer listed are named here.
    const gone = entries.filter((e) => !listed.has(e.id)).map(entryLabel);
    notifications.show({
      color: 'yellow',
      message:
        gone.length === 1
          ? `Retirado da exclusão por já não existir: ${gone.join('')}.`
          : `Retirados da exclusão por já não existirem: ${gone.join('; ')}.`,
    });
    onRetarget({ mode: 'many', entries: left });
  };

  const many = shown?.mode === 'many' ? shown.entries : [];

  return (
    <ConfirmModal
      opened={target !== null}
      onClose={close}
      onConfirm={confirm}
      title={shown?.mode === 'many' ? 'Excluir lançamentos' : 'Excluir lançamento'}
      confirmLabel="Excluir"
      loading={mutation.isPending || refreshing}
      error={mutation.error}
    >
      <Stack gap="xs">
        {shown?.mode === 'one' && (
          <Text inherit>O lançamento {entryLabel(shown.entry)} será excluído.</Text>
        )}
        {shown?.mode === 'many' && (
          <>
            <Text inherit>
              {many.length === 1
                ? '1 lançamento selecionado será excluído:'
                : `${String(many.length)} lançamentos selecionados serão excluídos, todos ou nenhum:`}
            </Text>
            <List size="sm" spacing={2}>
              {many.map((entry) => (
                <List.Item key={entry.id}>{entryLabel(entry)}</List.Item>
              ))}
            </List>
          </>
        )}
        <Text inherit c="dimmed">
          Lançamentos não são editados nem restaurados por esta tela. Os resultados já processados
          não mudam até um novo processamento a partir da data afetada.
        </Text>
      </Stack>
    </ConfirmModal>
  );
}
