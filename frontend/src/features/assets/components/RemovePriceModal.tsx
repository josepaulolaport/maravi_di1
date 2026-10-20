import { Checkbox, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';

import type { ReferencePrice, ReferencePriceDay } from '@/api/contract';
import { formatDate, formatPu, formatRate } from '@/shared/format';
import { ConfirmModal } from '@/shared/ui/ConfirmModal';

import { useRemoveReferencePrices } from '../hooks/usePrices';
import { SOURCE_LABELS } from './PriceCalendar';

interface RemovePriceModalProps {
  /** The date whose observations may be removed; `null` closes the modal. */
  day: ReferencePriceDay | null;
  onClose: () => void;
}

const observationLabel = (price: ReferencePrice) =>
  `${SOURCE_LABELS[price.source]}: PU ${formatPu(price.pu)}, taxa ${formatRate(price.rate)}`;

/**
 * "Remover" (§5): the user selects which prices of the date to remove, of any source (user
 * decision, 2026-10-18). The preferred one starts selected. A removed price is deleted; there
 * are no revisions to keep it (user, 2026-10-18).
 */
export function RemovePriceModal({ day, onClose }: RemovePriceModalProps) {
  return day ? <RemoveForm key={day.reference_date} day={day} onClose={onClose} /> : null;
}

function RemoveForm({ day, onClose }: { day: ReferencePriceDay; onClose: () => void }) {
  const [chosen, setChosen] = useState<string[]>([day.preferred.id]);
  const [empty, setEmpty] = useState(false);
  const remove = useRemoveReferencePrices();
  // Only ids still listed count: after a partial failure the removed ones drop out, and a
  // retry sends only what is left.
  const listed = chosen.filter((id) => day.sources.some((price) => price.id === id));
  const selected = listed.length > 0 ? listed : [day.preferred.id];

  // At least one observation stays selected, so "Remover" always has something to remove.
  const confirm = () =>
    remove.mutateAsync(selected).then(() => {
      notifications.show({
        color: 'teal',
        message:
          selected.length === 1
            ? 'Preço de referência removido.'
            : 'Preços de referência removidos.',
      });
      onClose();
    });

  return (
    <ConfirmModal
      opened
      onClose={onClose}
      onConfirm={confirm}
      title="Remover preço de referência"
      confirmLabel="Remover"
      loading={remove.isPending}
      error={remove.error}
    >
      <Stack gap="sm">
        <Text size="sm">Preços de {formatDate(day.reference_date)}:</Text>
        <Checkbox.Group
          value={selected}
          onChange={(value) => {
            setEmpty(value.length === 0);
            if (value.length > 0) setChosen(value);
          }}
          error={empty ? 'Selecione ao menos uma observação.' : undefined}
        >
          <Stack gap="xs">
            {day.sources.map((price) => (
              <Checkbox key={price.id} value={price.id} label={observationLabel(price)} />
            ))}
          </Stack>
        </Checkbox.Group>
      </Stack>
    </ConfirmModal>
  );
}
