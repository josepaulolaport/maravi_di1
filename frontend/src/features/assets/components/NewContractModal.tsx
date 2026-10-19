import { Button, Modal, Group, Stack, TextInput } from '@mantine/core';
import { DateInput } from '@mantine/dates';
import { notifications } from '@mantine/notifications';
import { IconCalendar } from '@tabler/icons-react';
import { useForm } from '@mantine/form';

import { parsePtBrDate } from '@/shared/format';
import { MessageAlert } from '@/shared/ui/MessageAlert';
import type { IsoDate, Product } from '@/api/contract';

import { useCreateInstrument } from '../hooks/useAssets';
import { splitProblem } from '@/shared/ui/problemMessages';

interface NewContractModalProps {
  product: Product;
  opened: boolean;
  onClose: () => void;
}

/**
 * "Novo contrato" (§3): a contract of this product with its own maturity. The backend
 * validates it (unique code, case-insensitive); its messages are shown on their fields.
 */
interface ContractValues {
  code: string;
  maturity: IsoDate | null;
}

// API field → form field, for the problem+json errors (OQ-15).
const FIELD_MAP = { code: 'code', maturity_date: 'maturity' };

export function NewContractModal({ product, opened, onClose }: NewContractModalProps) {
  const create = useCreateInstrument();
  // No client validation: the backend validates (required fields, unique code) and its
  // messages are shown on their fields (OQ-15).
  const form = useForm<ContractValues>({ initialValues: { code: '', maturity: null } });

  // While a save runs the modal stays open, so its confirmation is never lost.
  const close = () => {
    if (create.isPending) return;
    form.reset();
    create.reset();
    onClose();
  };

  const submit = form.onSubmit((values) => {
    create.mutate(
      { product_id: product.id, code: values.code.trim(), maturity_date: values.maturity ?? '' },
      {
        onSuccess: (instrument) => {
          notifications.show({ color: 'teal', message: `Contrato ${instrument.code} cadastrado.` });
          close();
        },
        // On the form, so editing a field clears its message (Mantine clears on change).
        onError: (error) => {
          form.setErrors(splitProblem(error, FIELD_MAP).fields);
        },
      },
    );
  });

  const { page } = splitProblem(create.error, FIELD_MAP);

  return (
    <Modal
      opened={opened}
      onClose={close}
      title="Novo contrato"
      centered
      size="lg"
      closeOnClickOutside={!create.isPending}
      closeOnEscape={!create.isPending}
      withCloseButton={!create.isPending}
      closeButtonProps={{ 'aria-label': 'Fechar' }}
    >
      <form onSubmit={submit} noValidate>
        <Stack gap="md">
          <TextInput label="Produto" value={product.code} readOnly />
          <TextInput
            label="Código"
            placeholder="DI1F31"
            withAsterisk
            {...form.getInputProps('code')}
          />
          <DateInput
            label="Vencimento"
            placeholder="DD/MM/AAAA"
            valueFormat="DD/MM/YYYY"
            dateParser={parsePtBrDate}
            withAsterisk
            leftSection={<IconCalendar size={16} stroke={1.5} />}
            {...form.getInputProps('maturity')}
          />
          <MessageAlert messages={page} />
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={close} disabled={create.isPending}>
              Cancelar
            </Button>
            <Button type="submit" loading={create.isPending}>
              Cadastrar contrato
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
