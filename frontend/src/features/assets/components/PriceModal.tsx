import { Alert, Select, Stack, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconInfoCircle } from '@tabler/icons-react';
import type { UseMutationResult } from '@tanstack/react-query';

import { typedPrice } from '@/shared/format';
import { useApiForm } from '@/shared/form/useApiForm';
import { useLastValue } from '@/shared/hooks/useLastValue';
import { useToday } from '@/shared/hooks/useToday';
import { ActionModal } from '@/shared/ui/ActionModal';
import { FormActions } from '@/shared/ui/FormActions';
import { MessageAlert } from '@/shared/ui/MessageAlert';
import type {
  InputKind,
  Instrument,
  IsoDate,
  ReferencePrice,
  SetReferencePriceRequest,
} from '@/api/contract';
import { PriceInput } from '@/shared/ui/PriceInput';

import { useSetReferencePrice } from '../hooks/usePrices';
import { lastDay } from '../model/calendarData';
import { DateField } from '@/shared/ui/DateField';

interface PriceModalProps {
  /** The contract the price is for; `null` with `contracts` lets the user pick it. */
  instrument: Instrument | null;
  /**
   * The contracts to pick from (the product page, OQ-48 item 1): the form then shows a
   * "Contrato" select, prefilled with `instrument` when given. Without it the contract is fixed.
   */
  contracts?: Instrument[];
  /** Whether `contracts` is still loading or failed to load (the select says so). */
  contractsStatus?: 'pending' | 'error' | 'success';
  /** The date the modal opens on; `null` closes it. */
  date: IsoDate | null;
  /** `saved` is the date of the price just recorded, when the modal closes after a save. */
  onClose: (saved?: IsoDate) => void;
}

/**
 * "Registrar preço de referência" (§11.2, §5): a MANUAL observation for one date, typed as PU
 * **or** rate. There is no computed field and no preview: the backend computes the other value
 * on save (OQ-19 item 7). A correction is the same call: it replaces the MANUAL price (OQ-26).
 */
export function PriceModal({
  instrument,
  contracts,
  contractsStatus = 'success',
  date,
  onClose,
}: PriceModalProps) {
  const save = useSetReferencePrice();
  const shownDate = useLastValue(date);
  const close = (saved?: IsoDate) => {
    save.reset();
    onClose(saved);
  };
  return (
    <ActionModal
      opened={date !== null}
      onClose={close}
      title="Registrar preço de referência"
      pending={save.isPending}
    >
      {shownDate !== null && (
        <PriceForm
          instrument={instrument}
          contracts={contracts}
          contractsStatus={contractsStatus}
          initialDate={shownDate}
          save={save}
          onDone={close}
        />
      )}
    </ActionModal>
  );
}

interface PriceFormProps {
  instrument: Instrument | null;
  contracts: Instrument[] | undefined;
  contractsStatus: 'pending' | 'error' | 'success';
  initialDate: IsoDate;
  save: UseMutationResult<ReferencePrice, Error, SetReferencePriceRequest>;
  onDone: (saved?: IsoDate) => void;
}

interface PriceValues extends Record<string, unknown> {
  assetId: string | null;
  date: IsoDate | null;
  kind: InputKind;
  price: string;
}

// API field → form field, for the problem+json errors (OQ-15); the value input owns pu, rate
// and input_kind, so every one of their messages is shown on it. The contract select, when
// there is one, shows asset_id's; otherwise they go above the form.
const FIELD_MAP = {
  reference_date: 'date',
  pu: 'price',
  rate: 'price',
  input_kind: 'price',
} as const;
const FIELD_MAP_WITH_CONTRACT = { ...FIELD_MAP, asset_id: 'assetId' } as const;

function PriceForm({
  instrument,
  contracts,
  contractsStatus,
  initialDate,
  save,
  onDone,
}: PriceFormProps) {
  const { form, pageErrors, clearPageErrors, onSubmit } = useApiForm<PriceValues>(
    {
      initialValues: { assetId: instrument?.id ?? null, date: initialDate, kind: 'PU', price: '' },
      validate: {
        assetId: (value) => (value ? null : 'Selecione o contrato.'),
        date: (value) => (value ? null : 'Informe a data.'),
        price: (value, values) => {
          if (!value.trim()) return values.kind === 'PU' ? 'Informe o PU.' : 'Informe a taxa.';
          return typedPrice(values.kind, value) === null ? 'Informe um número válido.' : null;
        },
      },
    },
    contracts ? FIELD_MAP_WITH_CONTRACT : FIELD_MAP,
  );

  const chosen = contracts?.find((c) => c.id === form.values.assetId) ?? instrument;
  // Nothing after today (OQ-14), nor after the contract's maturity (OQ-1).
  const today = useToday();
  const maxDate = lastDay(chosen?.maturity_date, today);

  const submit = onSubmit((values) => {
    const value = typedPrice(values.kind, values.price);
    if (!values.assetId || !values.date || value === null) return undefined;
    const base = { asset_id: values.assetId, reference_date: values.date };
    return save
      .mutateAsync(
        values.kind === 'PU'
          ? { ...base, input_kind: 'PU', pu: value }
          : { ...base, input_kind: 'RATE', rate: value },
      )
      .then((price) => {
        notifications.show({ color: 'teal', message: 'Preço de referência registrado.' });
        onDone(price.reference_date);
      });
  });

  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="md">
        {contracts ? (
          <Select
            label="Contrato"
            placeholder={
              contractsStatus === 'pending' ? 'Carregando contratos...' : 'Selecione o contrato'
            }
            withAsterisk
            searchable
            disabled={contractsStatus === 'pending'}
            data={contracts.map((c) => ({ value: c.id, label: c.code }))}
            {...form.getInputProps('assetId')}
            error={
              form.errors.assetId ??
              (contractsStatus === 'error' ? 'Não foi possível carregar os contratos.' : undefined)
            }
            onChange={(assetId: string | null) => {
              // Another contract: the previous one's errors no longer apply.
              form.clearErrors();
              clearPageErrors();
              save.reset();
              form.setFieldValue('assetId', assetId);
              const next = contracts.find((c) => c.id === assetId) ?? null;
              const limit = lastDay(next?.maturity_date, today);
              if (form.values.date !== null && form.values.date > limit) {
                form.setFieldValue('date', null);
                form.setFieldError('date', 'O contrato já venceu nesta data.');
              }
            }}
          />
        ) : (
          <TextInput label="Contrato" value={instrument?.code ?? ''} readOnly />
        )}
        <DateField
          label="Data de referência"
          maxDate={maxDate}
          limitMessage="O contrato já venceu nesta data."
          {...form.getInputProps('date')}
        />
        <PriceInput
          kind={form.values.kind}
          onKindChange={(kind) => {
            form.setValues({ kind, price: '' });
            form.clearFieldError('price');
          }}
          inputProps={form.getInputProps('price')}
          placeholder={{ PU: '89.250,31', RATE: '9,80' }}
        />
        <Alert color="gray" variant="light" icon={<IconInfoCircle size={18} />}>
          <Text size="sm">
            O registro não inicia um recálculo. Solicite um processamento para atualizar a carteira.
          </Text>
        </Alert>
        <MessageAlert messages={pageErrors} />
        <FormActions
          submitLabel="Salvar"
          onCancel={() => {
            onDone();
          }}
          pending={save.isPending}
        />
      </Stack>
    </form>
  );
}
