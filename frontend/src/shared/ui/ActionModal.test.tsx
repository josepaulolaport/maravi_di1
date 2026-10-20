import { TextInput } from '@mantine/core';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import { renderUi } from '@/test/render';

import { ActionModal } from './ActionModal';

function Harness({ pending = false }: { pending?: boolean }) {
  const [opened, setOpened] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpened(true);
        }}
      >
        Abrir
      </button>
      <ActionModal
        opened={opened}
        onClose={() => {
          setOpened(false);
        }}
        title="Novo"
        pending={pending}
      >
        <TextInput label="Código" />
      </ActionModal>
    </>
  );
}

describe('ActionModal', () => {
  it('§11 every opening starts blank, even when reopened while the last one closes', async () => {
    const user = userEvent.setup();
    renderUi(<Harness />);

    await user.click(screen.getByRole('button', { name: 'Abrir' }));
    await user.type(await screen.findByRole('textbox', { name: 'Código' }), 'DI1F31');
    await user.click(screen.getByRole('button', { name: 'Fechar' }));
    await user.click(screen.getByRole('button', { name: 'Abrir', hidden: true }));

    expect(await screen.findByRole('textbox', { name: 'Código' })).toHaveValue('');
  });

  it('OQ-15 cannot be closed while its action runs', async () => {
    const user = userEvent.setup();
    renderUi(<Harness pending />);

    await user.click(screen.getByRole('button', { name: 'Abrir' }));
    await screen.findByRole('dialog', { name: 'Novo' });
    await user.keyboard('{Escape}');

    expect(screen.getByRole('dialog', { name: 'Novo' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Fechar' })).not.toBeInTheDocument();
  });
});
