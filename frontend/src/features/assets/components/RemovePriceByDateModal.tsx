import { Button, Group, Modal, Stack, TextInput } from '@mantine/core';
import { IconCalendar } from '@tabler/icons-react';
import { useState } from 'react';

import type { Instrument, IsoDate, ReferencePriceDay } from '@/api/contract';
import { todayInSaoPaulo } from '@/shared/format';
import { MessageAlert } from '@/shared/ui/MessageAlert';
import { PastDateInput } from '@/shared/ui/PastDateInput';
import { problemMessages } from '@/shared/ui/problemMessages';

import { useReferencePriceDays } from '../hooks/usePrices';
import { RemovePriceModal } from './RemovePriceModal';

interface RemovePriceByDateModalProps {
  /** The contract whose price is removed; `null` closes the modal. */
  instrument: Instrument | null;
  onClose: () => void;
}

/**
 * "Remover preço" from the product page's contract list (OQ-48 item 1): the user picks a
 * date, then chooses which of that date's prices to remove, as on the contract page (§5). There
 * is no calendar here to pick the date from, so the date comes first.
 */
export function RemovePriceByDateModal({ instrument, onClose }: RemovePriceByDateModalProps) {
  return instrument ? (
    <DatePicker key={instrument.id} instrument={instrument} onClose={onClose} />
  ) : null;
}

const NO_PRICE = 'Nenhum preço registrado nesta data.';

function DatePicker({ instrument, onClose }: { instrument: Instrument; onClose: () => void }) {
  const [date, setDate] = useState<IsoDate | null>(null);
  const [missing, setMissing] = useState(false);
  // The date whose prices are read, once "Continuar" is pressed.
  const [lookup, setLookup] = useState<IsoDate | null>(null);
  const days = useReferencePriceDays(
    lookup === null ? null : { assetId: instrument.id, start: lookup, end: lookup },
  );
  // Only an answer read for this lookup counts: a cached one may be from before a write.
  const fresh = lookup !== null && days.isSuccess && !days.isFetching;
  const live = fresh ? (days.data.items.find((d) => d.reference_date === lookup) ?? null) : null;
  // Once found, the day stays on screen while the removal runs: when its last price goes, the
  // refetch finds nothing, and the removal modal must still finish (its confirmation, closing).
  const [found, setFound] = useState<ReferencePriceDay | null>(null);
  if (live !== null && live !== found) setFound(live);
  const day = live ?? found;

  if (day) return <RemovePriceModal day={day} onClose={onClose} />;

  // Nothing after today (OQ-14), nor after the contract's maturity (OQ-1).
  const today = todayInSaoPaulo();
  const maturity = instrument.maturity_date;
  const maxDate = maturity !== null && maturity < today ? maturity : today;
  const none = fresh && live === null;
  const error = missing ? 'Informe a data.' : none ? NO_PRICE : undefined;

  return (
    <Modal
      opened
      onClose={onClose}
      title="Remover preço de referência"
      centered
      closeButtonProps={{ 'aria-label': 'Fechar' }}
    >
      <Stack gap="md">
        <TextInput label="Contrato" value={instrument.code} readOnly />
        <PastDateInput
          today={today}
          label="Data de referência"
          maxDate={maxDate}
          limitMessage="O contrato já venceu nesta data."
          leftSection={<IconCalendar size={16} stroke={1.5} />}
          value={date}
          error={error}
          onChange={(value) => {
            setDate(value);
            setMissing(false);
            setLookup(null);
          }}
        />
        {lookup !== null && days.isError && !days.isFetching && (
          <MessageAlert messages={problemMessages(days.error)} />
        )}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            loading={lookup !== null && days.isFetching}
            onClick={() => {
              if (date === null) setMissing(true);
              // The same date again: read it again (after a failure, or a write elsewhere).
              else if (date === lookup) void days.refetch();
              else setLookup(date);
            }}
          >
            Continuar
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
