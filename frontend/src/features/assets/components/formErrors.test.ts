import { ApiError } from '@/api/http';

import { formErrors } from './formErrors';

const problem = (errors: { field: string | null; message: string }[]) =>
  new ApiError({
    type: 'about:blank',
    title: 'Dados inválidos',
    status: 422,
    detail: errors[0]?.message ?? 'Erro',
    errors: errors.map((e) => ({ code: 'VALIDATION_ERROR', ...e })),
  });

describe('formErrors', () => {
  it('§12 keeps field errors on the fields the form shows', () => {
    const result = formErrors(problem([{ field: 'pu', message: 'Informe um número válido.' }]), [
      'pu',
    ]);

    expect(result.fields).toEqual({ pu: 'Informe um número válido.' });
    expect(result.page).toEqual([]);
  });

  it('§12 keeps every message of a field, not only the first (OQ-15)', () => {
    const result = formErrors(
      problem([
        { field: 'pu', message: 'Informe um número válido.' },
        { field: 'pu', message: 'Use no máximo 10 casas decimais.' },
        { field: 'source', message: 'Fonte inválida.' },
        { field: 'source', message: 'Fonte desconhecida.' },
      ]),
      ['pu'],
    );

    expect(result.fields).toEqual({
      pu: 'Informe um número válido. Use no máximo 10 casas decimais.',
    });
    expect(result.page).toEqual(['Fonte inválida.', 'Fonte desconhecida.']);
  });

  it('§12 shows on the page a field error no input displays, so no message is lost', () => {
    const result = formErrors(
      problem([
        { field: 'source', message: 'Fonte inválida.' },
        { field: null, message: 'Erro geral.' },
      ]),
      ['pu'],
    );

    expect(result.page).toEqual(['Erro geral.', 'Fonte inválida.']);
  });

  it('§12 shows a generic message for an error that is not a problem+json', () => {
    expect(formErrors(new Error('x'), []).page).toEqual([
      'Ocorreu um erro inesperado. Tente novamente.',
    ]);
    expect(formErrors(null, [])).toEqual({ fields: {}, page: [] });
  });
});
