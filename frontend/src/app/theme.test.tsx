import { Button, Menu } from '@mantine/core';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderUi } from '@/test/render';

describe('theme', () => {
  it('§11 keeps a row menu open with its row: popovers are never hidden as detached', async () => {
    renderUi(
      <Menu>
        <Menu.Target>
          <Button>Ações</Button>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item>Ver detalhes</Menu.Item>
        </Menu.Dropdown>
      </Menu>,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'Ações' }));

    const item = await screen.findByRole('menuitem', { name: 'Ver detalhes' });
    // After the open transition; without the default it stays `display: none` in jsdom.
    await waitFor(() => {
      expect(item).toBeVisible();
    });
  });
});
