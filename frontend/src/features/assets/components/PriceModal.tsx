import {
  Alert,
  Button,
  Modal,
  Group,
  Input,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { DateInput } from '@mantine/dates';
import { notifications } from '@mantine/notifications';
import { IconAlertTriangle, IconCalendar, IconInfoCircle } from '@tabler/icons-react';
import { useId, useState } from 'react';

import type { InputKind, Instrument, IsoDate } from '@/api/contract';
import { parsePtBrDecimal, percentToFraction } from '@/shared/format';

import { useSetReferencePrice } from '../hooks/usePrices';
import { parsePtBrDate } from './dateInput';
import { formErrors } from './formErrors';

interface PriceModalProps {
  instrument: Instrument;
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
 * on save (OQ-19 item 7). A correction is the same call and overwrites the MANUAL price.
 */
export function PriceModal({ instrument, date, session, onClose }: PriceModalProps) {
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
          initialDate={date}
          save={save}
          onDone={close}
        />
      )}
    </Modal>
  );
}

interface PriceFormProps {
  instrument: Instrument;
  initialDate: IsoDate;
  save: ReturnType<typeof useSetReferencePrice>;
  onDone: (saved?: IsoDate) => void;
}

const SHOWN_FIELDS = ['reference_date', 'pu', 'rate', 'input_kind'] as const;

function PriceForm({ instrument, initialDate, save, onDone }: PriceFormProps) {
  const [date, setDate] = useState<string | null>(initialDate);
  const [kind, setKind] = useState<InputKind>('PU');
  const [text, setText] = useState('');
  const [invalidValue, setInvalidValue] = useState(false);
  const kindLabelId = useId();

  const submit = () => {
    const value = kind === 'PU' ? parsePtBrDecimal(text) : percentToFraction(text);
    if (value === null) {
      setInvalidValue(true);
      return;
    }
    setInvalidValue(false);
    // DateInput restores the last valid date when the field is left empty, so `date` is set.
    const base = { asset_id: instrument.id, reference_date: date ?? '' };
    save.mutate(
      kind === 'PU'
        ? { ...base, input_kind: 'PU', pu: value }
        : { ...base, input_kind: 'RATE', rate: value },
      {
        onSuccess: (price) => {
          notifications.show({ message: 'Preço de referência registrado.' });
          save.reset();
          onDone(price.reference_date);
        },
      },
    );
  };

  const { fields, page: pageErrors } = formErrors(save.error, SHOWN_FIELDS);
  // The value input owns the pu, rate and input_kind errors: every one of them is shown.
  const valueMessages = [fields.pu, fields.rate, fields.input_kind].filter(
    (message): message is string => message !== undefined,
  );
  const valueError = invalidValue
    ? 'Informe um número válido.'
    : valueMessages.length > 0
      ? valueMessages.join(' ')
      : undefined;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <Stack gap="md">
        <TextInput label="Contrato" value={instrument.code} readOnly />
        <DateInput
          label="Data de referência"
          placeholder="DD/MM/AAAA"
          valueFormat="DD/MM/YYYY"
          dateParser={parsePtBrDate}
          value={date}
          onChange={setDate}
          leftSection={<IconCalendar size={16} stroke={1.5} />}
          error={fields.reference_date}
        />
        <Input.Wrapper label="Forma de entrada" labelProps={{ id: kindLabelId }}>
          <SegmentedControl
            fullWidth
            role="radiogroup"
            aria-labelledby={kindLabelId}
            value={kind}
            onChange={(value) => {
              setKind(value);
              setText('');
              setInvalidValue(false);
            }}
            data={[
              { value: 'PU', label: 'PU' },
              { value: 'RATE', label: 'Taxa a.a.' },
            ]}
          />
        </Input.Wrapper>
        <TextInput
          label={kind === 'PU' ? 'PU' : 'Taxa a.a. (%)'}
          placeholder={kind === 'PU' ? '89.250,31' : '9,80'}
          inputMode="decimal"
          value={text}
          onChange={(event) => {
            setText(event.currentTarget.value);
          }}
          error={valueError}
        />
        <Alert color="gray" variant="light" icon={<IconInfoCircle size={18} />}>
          <Text size="sm">
            O registro não inicia um recálculo. Solicite um processamento para atualizar a carteira.
          </Text>
        </Alert>
        {pageErrors.length > 0 && (
          <Alert role="alert" color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
            {pageErrors.map((message) => (
              <Text key={message} size="sm">
                {message}
              </Text>
            ))}
          </Alert>
        )}
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
