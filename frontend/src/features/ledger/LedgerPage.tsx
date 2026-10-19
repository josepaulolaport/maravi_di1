import { Button, Group, List, Paper, Skeleton, Stack, Text, TextInput } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useDebouncedValue } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconCalendar, IconPlayerPlay, IconPlus, IconSearch, IconTrash } from '@tabler/icons-react';
import { useEffect, useMemo, useState } from 'react';

import type { IsoDate } from '@/api/contract';
import {
  type ProcessingDraft,
  ProcessingRequestModal,
} from '@/shared/processing/ProcessingRequestModal';
import { formatQuantity } from '@/shared/format';
import { ConfirmModal } from '@/shared/ui/ConfirmModal';
import { ErrorState } from '@/shared/ui/ErrorState';
import { LoadMore } from '@/shared/ui/LoadMore';

import { CashStrip } from './components/CashStrip';
import { EntriesTable, entryLabel } from './components/EntriesTable';
import { NewEntryModal } from './components/NewEntryModal';
import { type LedgerEntry, type SortDirection, toRow } from './entries';
import {
  useDeleteEntries,
  useEntries,
  useInstrumentTypes,
  useIsSavingEntry,
  useLedgerFilters,
} from './hooks/useLedger';
import { processCashDraft, processDraft } from './processingDraft';

type DeleteTarget = { mode: 'one'; entry: LedgerEntry } | { mode: 'many'; entries: LedgerEntry[] };

const SEARCH_DEBOUNCE_MS = 300;

const NO_SELECTION: ReadonlySet<string> = new Set();

/** "encontrados" once every page is read; "exibidos" while the backend has more (P21). */
const countLabel = (n: number, more: boolean) => {
  if (more) return `${formatQuantity(n)} lançamentos exibidos`;
  return n === 1 ? '1 lançamento encontrado' : `${formatQuantity(n)} lançamentos encontrados`;
};

/**
 * Lançamentos (spec §11.3): trades and cash movements in an inclusive range, with a search;
 * the cash strip for the range's end; one modal for compra, venda, aporte and retirada; single
 * and multiple delete with confirmation. There is no editing (§6.1).
 */
export function LedgerPage() {
  const filters = useLedgerFilters();
  const { start, end, search, today } = filters;
  const [sort, setSort] = useState<SortDirection>('desc');
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
          <SearchBox
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
        <div role="status" aria-label="Carregando lançamentos">
          <Skeleton h={320} />
        </div>
      ) : (
        <Paper>
          <EntriesTable
            entries={entries}
            instrumentTypeNames={typeNames}
            sort={sort}
            onToggleSort={() => {
              setSort((current) => (current === 'desc' ? 'asc' : 'desc'));
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
            {countLabel(entries.length, list.hasNextPage)}
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

/**
 * The search box follows the URL (`busca`): typing is debounced into it, and a change from
 * outside (a link, the sidebar) replaces what was typed instead of being overwritten by it.
 */
function SearchBox({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const [text, setText] = useState(value);
  const [seen, setSeen] = useState(value);
  // Whether the box holds the user's own typing (not yet in the URL, or already pushed).
  const [typing, setTyping] = useState(false);
  if (value !== seen) {
    setSeen(value);
    if (value !== text.trim()) {
      setText(value);
      setTyping(false);
    }
  }
  const [debounced] = useDebouncedValue(text, SEARCH_DEBOUNCE_MS);
  // Push only the user's typing once it has settled, so a stale debounced value is never
  // written back over a change from outside.
  useEffect(() => {
    if (typing && debounced === text && debounced.trim() !== value) onChange(debounced);
  }, [typing, debounced, text, value, onChange]);
  return (
    <TextInput
      aria-label="Buscar"
      placeholder="Buscar ativo ou lançamento..."
      leftSection={<IconSearch size={16} stroke={1.5} />}
      value={text}
      onChange={(event) => {
        setText(event.currentTarget.value);
        setTyping(true);
      }}
      w={300}
    />
  );
}

function DeleteDialog({ target, onClose }: { target: DeleteTarget | null; onClose: () => void }) {
  // One request for one entry or many, of either type (`POST /ledger/entries/deletions`).
  const mutation = useDeleteEntries();
  // The last target stays on screen while the dialog closes, so its text does not flicker.
  const [shown, setShown] = useState(target);
  if (target !== null && target !== shown) setShown(target);

  const close = () => {
    mutation.reset();
    onClose();
  };

  const confirm = () => {
    if (!target) return;
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
    });
  };

  const many = shown?.mode === 'many' ? shown.entries : [];

  return (
    <ConfirmModal
      opened={target !== null}
      onClose={close}
      onConfirm={confirm}
      title={shown?.mode === 'many' ? 'Excluir lançamentos' : 'Excluir lançamento'}
      confirmLabel="Excluir"
      loading={mutation.isPending}
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
          Lançamentos não são editados nem restaurados por esta tela. Os resultados publicados a
          partir da data afetada ficam desatualizados até um novo processamento.
        </Text>
      </Stack>
    </ConfirmModal>
  );
}
