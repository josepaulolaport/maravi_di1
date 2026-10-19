import { Button, Modal, Group, Stack, TextInput } from '@mantine/core';
import { DateInput } from '@mantine/dates';
import { notifications } from '@mantine/notifications';
import { IconCalendar } from '@tabler/icons-react';
import { useState } from 'react';

import { parsePtBrDate } from '@/shared/format';
import { MessageAlert } from '@/shared/ui/MessageAlert';
import type { Product } from '@/api/contract';

import { useCreateInstrument } from '../hooks/useAssets';
import { sameFields, splitProblem } from '@/shared/ui/problemMessages';

const SHOWN_FIELDS = ['code', 'maturity_date'] as const;

interface NewContractModalProps {
  product: Product;
  opened: boolean;
  onClose: () => void;
}

/**
 * "Novo contrato" (§3): a contract of this product with its own maturity. The backend
 * validates it (unique code, case-insensitive); its messages are shown on their fields.
 */
export function NewContractModal({ product, opened, onClose }: NewContractModalProps) {
  const [code, setCode] = useState('');
  const [maturity, setMaturity] = useState<string | null>(null);
  const create = useCreateInstrument();

  // While a save runs the modal stays open, so its confirmation is never lost.
  const close = () => {
    if (create.isPending) return;
    setCode('');
    setMaturity(null);
    create.reset();
    onClose();
  };

  const submit = () => {
    create.mutate(
      { product_id: product.id, code: code.trim(), maturity_date: maturity ?? '' },
      {
        onSuccess: (instrument) => {
          notifications.show({ message: `Contrato ${instrument.code} cadastrado.` });
          close();
        },
      },
    );
  };

  const { fields: fieldErrors, page: pageErrors } = splitProblem(
    create.error,
    sameFields(SHOWN_FIELDS),
  );

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
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Stack gap="md">
          <TextInput label="Produto" value={product.code} readOnly />
          <TextInput
            label="Código"
            placeholder="DI1F31"
            value={code}
            onChange={(event) => {
              setCode(event.currentTarget.value);
            }}
            error={fieldErrors.code}
          />
          <DateInput
            label="Vencimento"
            placeholder="DD/MM/AAAA"
            valueFormat="DD/MM/YYYY"
            dateParser={parsePtBrDate}
            value={maturity}
            onChange={setMaturity}
            leftSection={<IconCalendar size={16} stroke={1.5} />}
            error={fieldErrors.maturity_date}
          />
          <MessageAlert messages={pageErrors} />
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
