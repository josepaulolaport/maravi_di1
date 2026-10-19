import { Alert, Button, Group, Modal, Select, Stack, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconCalendar, IconInfoCircle } from '@tabler/icons-react';
import { useForm } from '@mantine/form';

import { MessageAlert } from '@/shared/ui/MessageAlert';
import type { InputKind, Instrument, IsoDate } from '@/api/contract';
import { todayInSaoPaulo } from '@/shared/format';
import { PriceInput, typedPrice } from '@/shared/ui/PriceInput';

import { useSetReferencePrice } from '../hooks/usePrices';
import { lastDay } from './calendarData';
import { splitProblem } from '@/shared/ui/problemMessages';
import { PastDateInput } from '@/shared/ui/PastDateInput';

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
  /** Bumped on every opening, so each one starts with a clean form. */
  session: number;
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
  session,
  onClose,
}: PriceModalProps) {
  const save = useSetReferencePrice();
  // While a save runs the modal stays open, so its confirmation is never lost.
  const close = (saved?: IsoDate) => {
    if (save.isPending) return;
    save.reset();
    onClose(saved);
  };
  return (
    <Modal
      opened={date !== null}
      onClose={() => {
        close();
      }}
      title="Registrar preço de referência"
      centered
      size="lg"
      closeOnClickOutside={!save.isPending}
      closeOnEscape={!save.isPending}
      withCloseButton={!save.isPending}
      closeButtonProps={{ 'aria-label': 'Fechar' }}
    >
      {date !== null && (
        <PriceForm
          key={session}
          instrument={instrument}
          contracts={contracts}
          contractsStatus={contractsStatus}
          initialDate={date}
          save={save}
          onDone={close}
        />
      )}
    </Modal>
  );
}

interface PriceFormProps {
  instrument: Instrument | null;
  contracts: Instrument[] | undefined;
  contractsStatus: 'pending' | 'error' | 'success';
  initialDate: IsoDate;
  save: ReturnType<typeof useSetReferencePrice>;
  onDone: (saved?: IsoDate) => void;
}

interface PriceValues {
  assetId: string | null;
  date: IsoDate | null;
  kind: InputKind;
  price: string;
}

// API field → form field, for the problem+json errors (OQ-15); the value input owns pu, rate
// and input_kind, so every one of their messages is shown on it.
const FIELD_MAP = { reference_date: 'date', pu: 'price', rate: 'price', input_kind: 'price' };
// With a contract select, its errors go on it.
const FIELD_MAP_WITH_CONTRACT = { ...FIELD_MAP, asset_id: 'assetId' };

function PriceForm({
  instrument,
  contracts,
  contractsStatus,
  initialDate,
  save,
  onDone,
}: PriceFormProps) {
  const fieldMap = contracts ? FIELD_MAP_WITH_CONTRACT : FIELD_MAP;
  const form = useForm<PriceValues>({
    initialValues: { assetId: instrument?.id ?? null, date: initialDate, kind: 'PU', price: '' },
    validate: {
      assetId: (value) => (value ? null : 'Selecione o contrato.'),
      date: (value) => (value ? null : 'Informe a data.'),
      price: (value, values) => {
        if (!value.trim()) return values.kind === 'PU' ? 'Informe o PU.' : 'Informe a taxa.';
        return typedPrice(values.kind, value) === null ? 'Informe um número válido.' : null;
      },
    },
  });

  const chosen = contracts?.find((c) => c.id === form.values.assetId) ?? instrument;
  // Nothing after today (OQ-14), nor after the contract's maturity (OQ-1).
  const today = todayInSaoPaulo();
  const maxDate = lastDay(chosen, today);

  const submit = form.onSubmit((values) => {
    const value = typedPrice(values.kind, values.price);
    if (!values.assetId || !values.date || value === null) return;
    const base = { asset_id: values.assetId, reference_date: values.date };
    save.mutate(
      values.kind === 'PU'
        ? { ...base, input_kind: 'PU', pu: value }
        : { ...base, input_kind: 'RATE', rate: value },
      {
        onSuccess: (price) => {
          notifications.show({ color: 'teal', message: 'Preço de referência registrado.' });
          save.reset();
          onDone(price.reference_date);
        },
        // On the form, so editing a field clears its message (Mantine clears on change).
        onError: (error) => {
          form.setErrors(splitProblem(error, fieldMap).fields);
        },
      },
    );
  });

  const { page } = splitProblem(save.error, fieldMap);

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
              save.reset();
              form.setFieldValue('assetId', assetId);
              const next = contracts.find((c) => c.id === assetId) ?? null;
              const limit = lastDay(next, today);
              if (form.values.date !== null && form.values.date > limit) {
                form.setFieldValue('date', null);
                form.setFieldError('date', 'O contrato já venceu nesta data.');
              }
            }}
          />
        ) : (
          <TextInput label="Contrato" value={instrument?.code ?? ''} readOnly />
        )}
        <PastDateInput
          today={today}
          label="Data de referência"
          placeholder="DD/MM/AAAA"
          valueFormat="DD/MM/YYYY"
          maxDate={maxDate}
          limitMessage="O contrato já venceu nesta data."
          leftSection={<IconCalendar size={16} stroke={1.5} />}
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
        <MessageAlert messages={page} />
        <Group justify="flex-end" gap="sm">
          <Button
            variant="default"
            onClick={() => {
              onDone();
            }}
            disabled={save.isPending}
          >
            Cancelar
          </Button>
          <Button type="submit" loading={save.isPending}>
            Salvar
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
