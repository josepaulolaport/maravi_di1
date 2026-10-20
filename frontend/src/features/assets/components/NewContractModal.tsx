import { Stack, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import type { UseMutationResult } from '@tanstack/react-query';

import { useApiForm } from '@/shared/form/useApiForm';
import { ActionModal } from '@/shared/ui/ActionModal';
import { DateField } from '@/shared/ui/DateField';
import { FormActions } from '@/shared/ui/FormActions';
import { MessageAlert } from '@/shared/ui/MessageAlert';
import type { CreateInstrumentRequest, Instrument, IsoDate, Product } from '@/api/contract';

import { useCreateInstrument } from '../hooks/useAssets';

interface NewContractModalProps {
  product: Product;
  opened: boolean;
  onClose: () => void;
}

interface ContractValues extends Record<string, unknown> {
  code: string;
  maturity: IsoDate | null;
}

// API field → form field, for the problem+json errors (OQ-15).
const FIELD_MAP = { code: 'code', maturity_date: 'maturity' } as const;

/**
 * "Novo contrato" (§3): a contract of this product with its own maturity. The backend
 * validates it (unique code, case-insensitive); its messages are shown on their fields.
 */
export function NewContractModal({ product, opened, onClose }: NewContractModalProps) {
  const create = useCreateInstrument();
  const close = () => {
    create.reset();
    onClose();
  };
  return (
    <ActionModal opened={opened} onClose={close} title="Novo contrato" pending={create.isPending}>
      <ContractForm product={product} create={create} onClose={close} />
    </ActionModal>
  );
}

interface ContractFormProps {
  product: Product;
  create: UseMutationResult<Instrument, Error, CreateInstrumentRequest>;
  onClose: () => void;
}

function ContractForm({ product, create, onClose }: ContractFormProps) {
  // No client validation: the backend validates (required fields, unique code) and its
  // messages are shown on their fields (OQ-15).
  const { form, pageErrors, onSubmit } = useApiForm<ContractValues>(
    { initialValues: { code: '', maturity: null } },
    FIELD_MAP,
  );

  const submit = onSubmit((values) =>
    create
      .mutateAsync({
        product_id: product.id,
        code: values.code.trim(),
        maturity_date: values.maturity ?? '',
      })
      .then((instrument) => {
        notifications.show({ color: 'teal', message: `Contrato ${instrument.code} cadastrado.` });
        onClose();
      }),
  );

  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="md">
        <TextInput label="Produto" value={product.code} readOnly />
        <TextInput
          label="Código"
          placeholder="DI1F31"
          withAsterisk
          {...form.getInputProps('code')}
        />
        <DateField
          label="Vencimento"
          withAsterisk
          // A maturity may be in the future (OQ-1 limits prices, not maturities).
          maxDate={null}
          {...form.getInputProps('maturity')}
        />
        <MessageAlert messages={pageErrors} />
        <FormActions
          submitLabel="Cadastrar contrato"
          onCancel={onClose}
          pending={create.isPending}
        />
      </Stack>
    </form>
  );
}
