import { Group, Stack, TextInput } from '@mantine/core';
import { TimeInput } from '@mantine/dates';
import { notifications } from '@mantine/notifications';

import { useApiForm } from '@/shared/form/useApiForm';
import { FormActions } from '@/shared/ui/FormActions';
import { MessageAlert } from '@/shared/ui/MessageAlert';
import type { IsoDate } from '@/api/contract';
import { formatDate, parsePtBrDecimal } from '@/shared/format';

import { useCreateEntry } from '../hooks/useLedger';
import { DateField } from '@/shared/ui/DateField';

import { nowInSaoPaulo, toIsoTime } from '../model/time';

export type CashSide = 'DEPOSIT' | 'WITHDRAWAL';

interface CashValues extends Record<string, unknown> {
  date: IsoDate | null;
  time: string;
  amount: string;
  description: string;
}

const FIELD_MAP = {
  date: 'date',
  time: 'time',
  cash_amount: 'amount',
  description: 'description',
} as const;

/** `ledger.entries.description VARCHAR(200)` (OQ-51). */
const DESCRIPTION_MAX_LENGTH = 200;

/**
 * Characters as the backend counts them: code points of the trimmed text (OQ-51). The input's
 * `maxLength` counts UTF-16 units of the raw text, a stricter guard, never a looser one.
 */
const descriptionLength = (value: string) => Array.from(value.trim()).length;

const LABELS = {
  DEPOSIT: { submit: 'Registrar aporte', done: 'Aporte registrado.' },
  WITHDRAWAL: { submit: 'Registrar retirada', done: 'Retirada registrada.' },
} as const;

/**
 * Aporte or retirada (§6.2): a date, a time and a positive amount; the side gives the sign, as
 * it does for a trade's quantity. The amount is sent exactly as typed, so the backend rejects
 * more than 2 places (OQ-3). Date and time are suggested as today and now in São Paulo, like a
 * trade (user, 2026-10-18: every entry has a time). An optional description of at most 200
 * characters is sent trimmed, and left out when blank (OQ-51).
 */
export function CashMovementForm({
  type,
  today,
  onDone,
}: {
  type: CashSide;
  today: IsoDate;
  onDone: () => void;
}) {
  const createMovement = useCreateEntry();

  const { form, pageErrors, onSubmit } = useApiForm<CashValues>(
    {
      initialValues: { date: today, time: nowInSaoPaulo(), amount: '', description: '' },
      validate: {
        date: (value) => (value ? null : 'Informe a data.'),
        time: (value) => (/^\d{2}:\d{2}(:\d{2})?$/.test(value) ? null : 'Informe a hora.'),
        amount: (value) => {
          if (!value.trim()) return 'Informe o valor.';
          const amount = parsePtBrDecimal(value);
          if (amount === null) return 'Informe um valor válido, como 1.234,56.';
          // The side gives the sign: a typed sign or a zero would turn an aporte into a retirada.
          return amount.startsWith('-') || /^0+(\.0+)?$/.test(amount)
            ? 'Informe um valor maior que zero.'
            : null;
        },
      },
    },
    FIELD_MAP,
  );

  const submit = onSubmit((values) => {
    const amount = parsePtBrDecimal(values.amount);
    const date = values.date;
    if (!date || amount === null) return undefined;
    const description = values.description.trim();
    return createMovement
      .mutateAsync({
        type: 'CASH',
        date,
        time: toIsoTime(values.time),
        cash_amount: type === 'DEPOSIT' ? amount : `-${amount}`,
        ...(description ? { description } : {}),
      })
      .then(() => {
        notifications.show({
          color: 'teal',
          message: `${LABELS[type].done} O caixa precisa ser processado a partir de ${formatDate(date)}: use o escopo Caixa.`,
        });
        onDone();
      });
  });

  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="md">
        <MessageAlert messages={pageErrors} />
        <Group grow align="flex-start">
          <DateField label="Data" withAsterisk {...form.getInputProps('date')} />
          <TimeInput label="Hora" withAsterisk {...form.getInputProps('time')} />
        </Group>
        <TextInput
          label="Valor (R$)"
          withAsterisk
          inputMode="decimal"
          placeholder="1.500.000,00"
          {...form.getInputProps('amount')}
        />
        <TextInput
          label="Descrição"
          description={`Opcional. ${String(descriptionLength(form.values.description))}/${String(DESCRIPTION_MAX_LENGTH)} caracteres.`}
          maxLength={DESCRIPTION_MAX_LENGTH}
          placeholder="Aporte inicial"
          {...form.getInputProps('description')}
        />
        <FormActions
          submitLabel={LABELS[type].submit}
          onCancel={onDone}
          pending={createMovement.isPending}
        />
      </Stack>
    </form>
  );
}
