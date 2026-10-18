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
 * "Remover" (§5): the user selects which current observations of the date to remove, of any
 * source (user decision, 2026-10-18). The preferred one starts selected. Removal is logical:
 * every revision stays in "Ver revisões".
 */
export function RemovePriceModal({ day, onClose }: RemovePriceModalProps) {
  return day ? <RemoveForm key={day.reference_date} day={day} onClose={onClose} /> : null;
}

function RemoveForm({ day, onClose }: { day: ReferencePriceDay; onClose: () => void }) {
  const [chosen, setChosen] = useState<string[]>([day.preferred.id]);
  const [empty, setEmpty] = useState(false);
  const remove = useRemoveReferencePrices();
  // Only ids still current count: after a partial failure the removed ones drop out, and a
  // retry sends only what is left.
  const current = chosen.filter((id) => day.current.some((price) => price.id === id));
  const selected = current.length > 0 ? current : [day.preferred.id];

  // At least one observation stays selected: ConfirmModal's double-click guard reopens only
  // when an attempt finishes, so an empty "Remover" must never reach `onConfirm`.
  const confirm = () => {
    remove.mutate(selected, {
      onSuccess: () => {
        notifications.show({
          message:
            selected.length === 1
              ? 'Preço de referência removido.'
              : 'Preços de referência removidos.',
        });
        onClose();
      },
    });
  };

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
        <Text size="sm">Observações atuais de {formatDate(day.reference_date)}:</Text>
        <Checkbox.Group
          value={selected}
          onChange={(value) => {
            setEmpty(value.length === 0);
            if (value.length > 0) setChosen(value);
          }}
          error={empty ? 'Selecione ao menos uma observação.' : undefined}
        >
          <Stack gap="xs">
            {day.current.map((price) => (
              <Checkbox key={price.id} value={price.id} label={observationLabel(price)} />
            ))}
          </Stack>
        </Checkbox.Group>
        <Text size="xs" c="dimmed">
          As revisões removidas continuam em “Ver revisões”.
        </Text>
      </Stack>
    </ConfirmModal>
  );
}
