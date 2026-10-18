import { Alert, Button, Group, Stack, Text, TextInput } from '@mantine/core';
import { DateInput } from '@mantine/dates';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useState } from 'react';

import type { CashMovementType, IsoDate } from '@/api/contract';
import { parsePtBrDecimal } from '@/shared/format';

import { useCreateCashMovement } from '../hooks/useLedger';
import { parsePtBrDate, splitErrors } from './formSupport';

interface CashValues {
  date: IsoDate | null;
  amount: string;
}

const FIELD_MAP: Record<string, keyof CashValues> = {
  movement_date: 'date',
  amount: 'amount',
};

const LABELS = {
  DEPOSIT: { submit: 'Registrar aporte', done: 'Aporte registrado.' },
  WITHDRAWAL: { submit: 'Registrar retirada', done: 'Retirada registrada.' },
} as const;

/**
 * Aporte or retirada (§6.2): a date and a positive amount; the type gives the direction.
 * The amount is sent exactly as typed, so the backend rejects more than 2 places (OQ-3).
 * No description (user, 2026-10-18, GAP-I-2: "no need to have a description at all").
 */
export function CashMovementForm({
  type,
  today,
  onDone,
}: {
  type: CashMovementType;
  today: IsoDate;
  onDone: () => void;
}) {
  const createMovement = useCreateCashMovement();
  const [pageErrors, setPageErrors] = useState<string[]>([]);

  const form = useForm<CashValues>({
    initialValues: { date: today, amount: '' },
    validate: {
      date: (value) => (value ? null : 'Informe a data.'),
      amount: (value) => {
        if (!value.trim()) return 'Informe o valor.';
        return parsePtBrDecimal(value) === null ? 'Informe um valor válido, como 1.234,56.' : null;
      },
    },
  });

  const submit = form.onSubmit((values) => {
    const amount = parsePtBrDecimal(values.amount);
    if (!values.date || amount === null) return;
    setPageErrors([]);
    createMovement.mutate(
      { movement_date: values.date, movement_type: type, amount },
      {
        onSuccess: () => {
          notifications.show({ color: 'teal', message: LABELS[type].done });
          onDone();
        },
        onError: (error) => {
          const { fields, page } = splitErrors(error, FIELD_MAP);
          form.setErrors(fields);
          setPageErrors(page);
        },
      },
    );
  });

  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="md">
        {pageErrors.length > 0 && (
          <Alert role="alert" color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
            <Stack gap={4}>
              {pageErrors.map((message, index) => (
                <Text key={`${String(index)}-${message}`} size="sm">
                  {message}
                </Text>
              ))}
            </Stack>
          </Alert>
        )}
        <DateInput
          label="Data"
          withAsterisk
          valueFormat="DD/MM/YYYY"
          dateParser={parsePtBrDate}
          maxDate={today}
          placeholder="DD/MM/AAAA"
          {...form.getInputProps('date')}
        />
        <TextInput
          label="Valor (R$)"
          withAsterisk
          inputMode="decimal"
          placeholder="1.500.000,00"
          {...form.getInputProps('amount')}
        />
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onDone} disabled={createMovement.isPending}>
            Cancelar
          </Button>
          <Button type="submit" loading={createMovement.isPending}>
            {LABELS[type].submit}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
