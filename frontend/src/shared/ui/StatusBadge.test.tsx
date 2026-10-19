import { screen } from '@testing-library/react';

import { renderUi } from '@/test/render';

import { StatusBadge } from './StatusBadge';

describe('StatusBadge', () => {
  it('§11 shows the status as text, so colour is never the only signal', () => {
    renderUi(<StatusBadge label="Concluído com pendências" color="yellow" />);

    expect(screen.getByText('Concluído com pendências')).toBeVisible();
  });

  it('§10.3 is not a live region by default, so a table of jobs is not announced on each poll', () => {
    renderUi(<StatusBadge label="Falhou" color="red" />);

    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('§10.3 announces changes when marked live (the job being followed)', () => {
    renderUi(<StatusBadge label="Processando" color="blue" live />);

    expect(screen.getByRole('status')).toHaveTextContent('Processando');
  });
});
