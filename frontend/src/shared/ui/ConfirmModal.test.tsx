import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ApiError } from '@/api/http';
import { renderUi } from '@/test/render';

import { ConfirmModal } from './ConfirmModal';

function setup(props: Partial<Parameters<typeof ConfirmModal>[0]> = {}) {
  const onClose = vi.fn();
  const onConfirm = vi.fn();
  renderUi(
    <ConfirmModal
      opened
      onClose={onClose}
      onConfirm={onConfirm}
      title="Excluir lançamentos?"
      confirmLabel="Excluir"
      {...props}
    >
      2 lançamentos serão excluídos.
    </ConfirmModal>,
  );
  return { onClose, onConfirm, user: userEvent.setup() };
}

describe('ConfirmModal', () => {
  it('§6.1 shows the title and the summary in a dialog', async () => {
    setup();

    const dialog = await screen.findByRole('dialog', { name: 'Excluir lançamentos?' });
    expect(dialog).toHaveTextContent('2 lançamentos serão excluídos.');
  });

  it('§6.1 confirms with the given label', async () => {
    const { onConfirm, onClose, user } = setup();

    await user.click(await screen.findByRole('button', { name: 'Excluir' }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('§6.1 goes back with "Voltar" without confirming', async () => {
    const { onConfirm, onClose, user } = setup();

    await user.click(await screen.findByRole('button', { name: 'Voltar' }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('§6.1 blocks a second confirmation while the action runs', async () => {
    const { onConfirm, user } = setup({ loading: true });

    const confirm = await screen.findByRole('button', { name: 'Excluir' });
    expect(confirm).toBeDisabled();
    await user.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Voltar' })).toBeDisabled();
  });

  it('OQ-15 shows the API message when the action fails', async () => {
    const error = new ApiError({
      type: 'about:blank',
      title: 'Conflito',
      status: 409,
      errors: [
        {
          code: 'JOB_NOT_CANCELLABLE',
          message: 'O processamento já terminou e não pode ser cancelado.',
          field: null,
        },
      ],
    });
    setup({ error });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'O processamento já terminou e não pode ser cancelado.',
    );
  });

  it('§6.1 confirms once on a double click, before the parent reports loading', async () => {
    const { onConfirm, user } = setup();

    await user.dblClick(await screen.findByRole('button', { name: 'Excluir' }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('§6.1 can confirm again once the previous attempt has finished', async () => {
    const onConfirm = vi.fn();
    const props = {
      opened: true,
      onClose: vi.fn(),
      onConfirm,
      title: 'Cancelar processamento?',
      confirmLabel: 'Confirmar cancelamento',
    };
    const user = userEvent.setup();
    const { rerender } = renderUi(<ConfirmModal {...props}>Resumo</ConfirmModal>);
    const confirm = await screen.findByRole('button', { name: 'Confirmar cancelamento' });

    await user.click(confirm);
    rerender(
      <ConfirmModal {...props} loading>
        Resumo
      </ConfirmModal>,
    );
    rerender(
      <ConfirmModal {...props} error={new Error('x')}>
        Resumo
      </ConfirmModal>,
    );
    await user.click(screen.getByRole('button', { name: 'Confirmar cancelamento' }));

    expect(onConfirm).toHaveBeenCalledTimes(2);
  });

  it('§6.1 stays guarded when the parent clears the error before reporting loading', async () => {
    const onConfirm = vi.fn();
    const props = {
      opened: true,
      onClose: vi.fn(),
      onConfirm,
      title: 'Cancelar processamento?',
      confirmLabel: 'Confirmar cancelamento',
    };
    const user = userEvent.setup();
    const { rerender } = renderUi(
      <ConfirmModal {...props} error={new Error('x')}>
        Resumo
      </ConfirmModal>,
    );

    // Retry: the parent clears the old error at once and reports loading a render later.
    await user.click(await screen.findByRole('button', { name: 'Confirmar cancelamento' }));
    rerender(<ConfirmModal {...props}>Resumo</ConfirmModal>);
    await user.click(screen.getByRole('button', { name: 'Confirmar cancelamento' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    // The retry fails without the parent ever reporting loading: a new error reopens it.
    rerender(
      <ConfirmModal {...props} error={new Error('y')}>
        Resumo
      </ConfirmModal>,
    );
    await user.click(screen.getByRole('button', { name: 'Confirmar cancelamento' }));
    expect(onConfirm).toHaveBeenCalledTimes(2);
  });

  it('OQ-15 shows a field-bound API message too, since a dialog has no fields', async () => {
    const error = new ApiError({
      type: 'about:blank',
      title: 'Dados inválidos',
      status: 422,
      errors: [
        {
          code: 'INVALID_RANGE',
          message: 'A data inicial deve ser anterior ou igual à data final.',
          field: 'end_date',
        },
      ],
    });
    setup({ error });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'A data inicial deve ser anterior ou igual à data final.',
    );
  });

  it('§11 names the close button in pt-BR', async () => {
    setup();

    expect(await screen.findByRole('button', { name: 'Fechar' })).toBeInTheDocument();
  });

  it('OQ-15 shows a generic pt-BR message for an unexpected error', async () => {
    setup({ error: new Error('boom') });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Ocorreu um erro inesperado. Tente novamente.',
    );
  });
});
