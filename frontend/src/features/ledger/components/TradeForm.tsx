import {
  Alert,
  Button,
  Group,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { DateInput, TimeInput } from '@mantine/dates';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useState } from 'react';

import type { CreateTradeRequest, InputKind, IsoDate } from '@/api/contract';
import { parsePtBrDecimal, percentToFraction } from '@/shared/format';

import { useCreateTrade, useInstruments } from '../hooks/useLedger';
import { nowInSaoPaulo, parsePtBrDate, splitErrors, toIsoTime } from './formSupport';

export type TradeSide = 'BUY' | 'SELL';

interface TradeValues {
  assetId: string | null;
  date: IsoDate | null;
  time: string;
  quantity: number | string;
  inputKind: InputKind;
  price: string;
}

// API field → form field, for the problem+json errors (OQ-15).
const FIELD_MAP: Record<string, keyof TradeValues> = {
  asset_id: 'assetId',
  trade_date: 'date',
  trade_time: 'time',
  signed_quantity: 'quantity',
  execution_pu: 'price',
  execution_rate: 'price',
  input_kind: 'price',
};

const LABELS = {
  BUY: { submit: 'Registrar compra', done: 'Compra registrada.' },
  SELL: { submit: 'Registrar venda', done: 'Venda registrada.' },
} as const;

const PRICE_LABEL: Record<InputKind, string> = { PU: 'PU', RATE: 'Taxa a.a. (%)' };

// OQ-3: a typed PU has at most 10 places; a typed rate at most 12 as a fraction, which is 10
// in the percent the user types. More places are rejected by the backend, never rounded.
const PRICE_DESCRIPTION: Record<InputKind, string> = {
  PU: 'Até 10 casas decimais',
  RATE: 'Em % ao ano, até 10 casas decimais',
};

/** The typed PU, or the typed percent as a fraction (10,45 → 0.1045); `null` if invalid. */
function typedPrice(values: TradeValues): string | null {
  return values.inputKind === 'PU'
    ? parsePtBrDecimal(values.price)
    : percentToFraction(values.price);
}

/**
 * Compra or venda (§6.1). The user types PU **or** rate; the backend computes the other on
 * save and there is no preview (OQ-19 item 7). The quantity is typed positive; the side gives
 * the sign. Date and time are required, suggested as today and now in São Paulo (OQ-13).
 */
export function TradeForm({
  side,
  today,
  onDone,
}: {
  side: TradeSide;
  today: IsoDate;
  onDone: () => void;
}) {
  const instruments = useInstruments();
  const createTrade = useCreateTrade();
  const [pageErrors, setPageErrors] = useState<string[]>([]);

  const form = useForm<TradeValues>({
    initialValues: {
      assetId: null,
      date: today,
      time: nowInSaoPaulo(),
      quantity: '',
      inputKind: 'PU',
      price: '',
    },
    validate: {
      assetId: (value) => (value ? null : 'Selecione um contrato.'),
      date: (value) => (value ? null : 'Informe a data.'),
      time: (value) => (/^\d{2}:\d{2}(:\d{2})?$/.test(value) ? null : 'Informe a hora.'),
      quantity: (value) =>
        typeof value === 'number' && Number.isInteger(value) && value > 0
          ? null
          : 'Informe uma quantidade inteira maior que zero.',
      price: (value, values) => {
        if (!value.trim()) return values.inputKind === 'PU' ? 'Informe o PU.' : 'Informe a taxa.';
        return typedPrice(values) === null ? 'Informe um número válido, como 1.234,56.' : null;
      },
    },
  });

  const submit = form.onSubmit((values) => {
    const price = typedPrice(values);
    if (!values.assetId || !values.date || typeof values.quantity !== 'number' || !price) return;
    const base = {
      asset_id: values.assetId,
      trade_date: values.date,
      trade_time: toIsoTime(values.time),
      signed_quantity: side === 'BUY' ? values.quantity : -values.quantity,
    };
    const body: CreateTradeRequest =
      values.inputKind === 'PU'
        ? { ...base, input_kind: 'PU', execution_pu: price }
        : { ...base, input_kind: 'RATE', execution_rate: price };
    setPageErrors([]);
    createTrade.mutate(body, {
      onSuccess: () => {
        notifications.show({ color: 'teal', message: LABELS[side].done });
        onDone();
      },
      onError: (error) => {
        const { fields, page } = splitErrors(error, FIELD_MAP);
        form.setErrors(fields);
        setPageErrors(page);
      },
    });
  });

  const contractOptions = (instruments.data?.items ?? []).map((i) => ({
    value: i.id,
    label: i.code,
  }));

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
        <Select
          label="Contrato"
          placeholder={instruments.isPending ? 'Carregando contratos...' : 'Selecione'}
          data={contractOptions}
          // Inside the drawer, so the options are not hidden behind its modal layer.
          comboboxProps={{ withinPortal: false }}
          disabled={instruments.isPending}
          withAsterisk
          {...form.getInputProps('assetId')}
          {...(instruments.isError ? { error: 'Não foi possível carregar os contratos.' } : {})}
        />
        <Group grow align="flex-start">
          <DateInput
            label="Data"
            withAsterisk
            valueFormat="DD/MM/YYYY"
            dateParser={parsePtBrDate}
            maxDate={today}
            placeholder="DD/MM/AAAA"
            {...form.getInputProps('date')}
          />
          <TimeInput label="Hora" withAsterisk {...form.getInputProps('time')} />
        </Group>
        <NumberInput
          label="Quantidade"
          description="Número de contratos, sempre positivo"
          withAsterisk
          allowDecimal={false}
          allowNegative={false}
          min={1}
          hideControls
          {...form.getInputProps('quantity')}
        />
        <Stack gap={6}>
          <Text size="sm" fw={500} id="trade-input-kind">
            Forma de entrada
          </Text>
          <SegmentedControl
            aria-labelledby="trade-input-kind"
            data={[
              { value: 'PU', label: PRICE_LABEL.PU },
              { value: 'RATE', label: PRICE_LABEL.RATE },
            ]}
            value={form.values.inputKind}
            onChange={(value) => {
              form.setValues({ inputKind: value, price: '' });
              form.clearFieldError('price');
            }}
          />
        </Stack>
        <TextInput
          label={PRICE_LABEL[form.values.inputKind]}
          description={PRICE_DESCRIPTION[form.values.inputKind]}
          withAsterisk
          inputMode="decimal"
          placeholder={form.values.inputKind === 'PU' ? '89.006,46' : '10,45'}
          {...form.getInputProps('price')}
        />
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onDone} disabled={createTrade.isPending}>
            Cancelar
          </Button>
          <Button type="submit" loading={createTrade.isPending}>
            {LABELS[side].submit}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
