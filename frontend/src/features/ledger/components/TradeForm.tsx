import {
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
import { useMemo, useState } from 'react';

import { useAllInstruments, useAllProducts } from '@/shared/queries';
import { MessageAlert } from '@/shared/ui/MessageAlert';
import type { CreateTradeEntryRequest, InputKind, IsoDate } from '@/api/contract';
import { formatDate, parsePtBrDate, parsePtBrDecimal, percentToFraction } from '@/shared/format';

import { useCreateEntry } from '../hooks/useLedger';
import { splitProblem } from '@/shared/ui/problemMessages';

import { nowInSaoPaulo, toIsoTime } from './formSupport';

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
  date: 'date',
  time: 'time',
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
 * The contract picker's options: every contract, or those whose product is of the chosen
 * asset class. The class names come from the products, so only classes with a product show.
 */
function useContractOptions(assetClassId: string | null) {
  const instruments = useAllInstruments();
  const products = useAllProducts();
  const classOf = useMemo(
    () => new Map((products.data?.items ?? []).map((p) => [p.id, String(p.asset_class.id)])),
    [products.data],
  );
  const classOptions = useMemo(() => {
    const names = new Map(
      (products.data?.items ?? []).map((p) => [String(p.asset_class.id), p.asset_class.name]),
    );
    return [...names].map(([value, label]) => ({ value, label }));
  }, [products.data]);
  const items = instruments.data?.items ?? [];
  const contractOptions = items
    .filter((i) => assetClassId === null || classOf.get(i.product_id) === assetClassId)
    .map((i) => ({ value: i.id, label: i.code }));
  /** The asset class of a contract, by its id. */
  const classOfContract = (instrumentId: string) => {
    const instrument = items.find((i) => i.id === instrumentId);
    return instrument ? classOf.get(instrument.product_id) : undefined;
  };
  return {
    classOptions,
    contractOptions,
    classOfContract,
    pending: instruments.isPending || products.isPending,
    /** Without products the class filter is unavailable; the contracts still are. */
    classesFailed: products.isError,
    contractsFailed: instruments.isError,
  };
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
  const createTrade = useCreateEntry();
  const [pageErrors, setPageErrors] = useState<string[]>([]);
  const [assetClassId, setAssetClassId] = useState<string | null>(null);
  const contracts = useContractOptions(assetClassId);

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
      type: 'TRADE' as const,
      asset_id: values.assetId,
      date: values.date,
      time: toIsoTime(values.time),
      signed_quantity: side === 'BUY' ? values.quantity : -values.quantity,
    };
    const body: CreateTradeEntryRequest =
      values.inputKind === 'PU'
        ? { ...base, input_kind: 'PU', execution_pu: price }
        : { ...base, input_kind: 'RATE', execution_rate: price };
    setPageErrors([]);
    createTrade.mutate(body, {
      onSuccess: () => {
        notifications.show({
          color: 'teal',
          message: `${LABELS[side].done} Caixa e posições precisam ser processados a partir de ${formatDate(body.date)}: use o escopo Tudo.`,
        });
        onDone();
      },
      onError: (error) => {
        const { fields, page } = splitProblem(error, FIELD_MAP);
        form.setErrors(fields);
        setPageErrors(page);
      },
    });
  });

  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="md">
        <MessageAlert messages={pageErrors} />
        <Group grow align="flex-start">
          <Select
            label="Classe de ativo"
            placeholder="Todas as classes"
            data={contracts.classOptions}
            comboboxProps={{ withinPortal: false }}
            disabled={contracts.pending || contracts.classesFailed}
            {...(contracts.classesFailed
              ? { error: 'Não foi possível carregar as classes de ativo.' }
              : {})}
            clearable
            value={assetClassId}
            onChange={(value) => {
              setAssetClassId(value);
              // A contract of another class is no longer offered: it must be chosen again.
              const chosen = form.values.assetId;
              if (chosen && value !== null && contracts.classOfContract(chosen) !== value) {
                form.setFieldValue('assetId', null);
              }
            }}
          />
          <Select
            label="Contrato"
            placeholder={contracts.pending ? 'Carregando contratos...' : 'Buscar contrato'}
            data={contracts.contractOptions}
            searchable
            nothingFoundMessage="Nenhum contrato encontrado"
            comboboxProps={{ withinPortal: false }}
            disabled={contracts.pending}
            withAsterisk
            {...form.getInputProps('assetId')}
            {...(contracts.contractsFailed
              ? { error: 'Não foi possível carregar os contratos.' }
              : {})}
          />
        </Group>
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
