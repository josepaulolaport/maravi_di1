import { List, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useEffect, useRef, useState } from 'react';

import { ApiError } from '@/api/http';
import { useLastValue } from '@/shared/hooks/useLastValue';
import { ConfirmModal } from '@/shared/ui/ConfirmModal';
import { countLabel } from '@/shared/format';
import { problemMessages } from '@/shared/ui/problemMessages';

import { entryLabel, type LedgerEntry } from '../model/entries';
import { useDeleteEntries } from '../hooks/useLedger';

export type DeleteTarget =
  { mode: 'one'; entry: LedgerEntry } | { mode: 'many'; entries: LedgerEntry[] };

/** Ids of the entries the list shows once it is read again. */
type RefreshListed = () => Promise<ReadonlySet<string>>;

/**
 * Deletes one entry or the selected ones, after confirmation (§6.1). A 404 means an entry is
 * already gone (deleted elsewhere) and nothing was deleted (OQ-32): the list is read again and
 * the dialog keeps only the entries still listed, so "Excluir" can be retried; when none is
 * left, it closes and says so.
 */
export function DeleteDialog({
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
  // Still shown while the dialog closes.
  const shown = useLastValue(target);

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
    if (!target) return Promise.resolve();
    const entries = target.mode === 'one' ? [target.entry] : target.entries;
    return mutation.mutateAsync(entries).then(
      () => {
        notifications.show({
          color: 'teal',
          message:
            entries.length === 1
              ? 'Lançamento excluído.'
              : `${countLabel(entries.length, 'lançamento excluído', 'lançamentos excluídos')}.`,
        });
        close();
      },
      (error: unknown) =>
        error instanceof ApiError && error.status === 404
          ? dropVanished(target, problemMessages(error).join(' '))
          : undefined,
    );
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
                : `${countLabel(many.length, 'lançamento selecionado', 'lançamentos selecionados')} serão excluídos, todos ou nenhum:`}
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
