import { Button, Group, Modal, Stack, TextInput } from '@mantine/core';
import { IconCalendar } from '@tabler/icons-react';
import { useState } from 'react';

import type { Instrument, IsoDate } from '@/api/contract';
import { todayInSaoPaulo } from '@/shared/format';
import { PastDateInput } from '@/shared/ui/PastDateInput';

import { useReferencePriceDays } from '../hooks/usePrices';
import { RemovePriceModal } from './RemovePriceModal';

interface RemovePriceByDateModalProps {
  /** The contract whose price is removed; `null` closes the modal. */
  instrument: Instrument | null;
  onClose: () => void;
}

/**
 * "Remover preço" from the product page's contract list (user, 2026-10-19): the user picks a
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
  const days = useReferencePriceDays(instrument.id, lookup ?? '', lookup ?? '', lookup !== null);
  const day =
    lookup !== null ? (days.data?.items.find((d) => d.reference_date === lookup) ?? null) : null;
  const none = lookup !== null && days.isSuccess && day === null;

  // The date's prices are listed by the same modal as on the contract page.
  if (day) return <RemovePriceModal day={day} onClose={onClose} />;

  // Nothing after today (OQ-14), nor after the contract's maturity (OQ-1).
  const today = todayInSaoPaulo();
  const maturity = instrument.maturity_date;
  const maxDate = maturity !== null && maturity < today ? maturity : today;
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
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            loading={lookup !== null && days.isFetching}
            onClick={() => {
              if (date === null) setMissing(true);
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
