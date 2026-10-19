import { Modal, SegmentedControl, Stack } from '@mantine/core';
import { useState } from 'react';

import type { IsoDate } from '@/api/contract';

import { CashMovementForm, type CashSide } from './CashMovementForm';
import { TradeForm, type TradeSide } from './TradeForm';

type EntryGroup = 'TRADE' | 'CASH';

interface NewEntryModalProps {
  opened: boolean;
  onClose: () => void;
  today: IsoDate;
  /** A save is running: the modal stays open until its result is shown. */
  saving: boolean;
}

/**
 * "Novo lançamento" (§11.3, user 2026-10-18): one modal that switches between an operação
 * (compra or venda) and a cash movement (aporte or retirada), each with its own fields.
 */
export function NewEntryModal({ opened, onClose, today, saving }: NewEntryModalProps) {
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Novo lançamento"
      size="lg"
      centered
      closeOnEscape={!saving}
      closeOnClickOutside={!saving}
      withCloseButton={!saving}
      closeButtonProps={{ 'aria-label': 'Fechar' }}
    >
      {/* Mounted only while open, so every opening starts from a blank form. */}
      {opened && <NewEntry today={today} onDone={onClose} saving={saving} />}
    </Modal>
  );
}

function NewEntry({
  today,
  onDone,
  saving,
}: {
  today: IsoDate;
  onDone: () => void;
  saving: boolean;
}) {
  const [group, setGroup] = useState<EntryGroup>('TRADE');
  const [side, setSide] = useState<TradeSide>('BUY');
  const [cashType, setCashType] = useState<CashSide>('DEPOSIT');

  return (
    <Stack gap="md">
      <SegmentedControl
        aria-label="Tipo de lançamento"
        fullWidth
        disabled={saving}
        data={[
          { value: 'TRADE', label: 'Operação' },
          { value: 'CASH', label: 'Caixa' },
        ]}
        value={group}
        onChange={(value) => {
          setGroup(value);
        }}
      />
      {group === 'TRADE' ? (
        <>
          <SegmentedControl
            aria-label="Tipo de operação"
            fullWidth
            disabled={saving}
            data={[
              { value: 'BUY', label: 'Compra' },
              { value: 'SELL', label: 'Venda' },
            ]}
            value={side}
            onChange={(value) => {
              setSide(value);
            }}
          />
          <TradeForm side={side} today={today} onDone={onDone} />
        </>
      ) : (
        <>
          <SegmentedControl
            aria-label="Tipo de movimentação"
            fullWidth
            disabled={saving}
            data={[
              { value: 'DEPOSIT', label: 'Aporte' },
              { value: 'WITHDRAWAL', label: 'Retirada' },
            ]}
            value={cashType}
            onChange={(value) => {
              setCashType(value);
            }}
          />
          <CashMovementForm type={cashType} today={today} onDone={onDone} />
        </>
      )}
    </Stack>
  );
}
