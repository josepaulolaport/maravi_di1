import type { FieldError } from '@/api/contract';
import { ApiError } from '@/api/http';

import { problemMessages, sameFields, splitProblem } from './problemMessages';

const problem = (errors: FieldError[]) =>
  new ApiError({
    type: 'about:blank',
    title: 'Dados inválidos',
    status: 422,
    detail: 'Detalhe',
    errors,
  });

describe('problemMessages (OQ-15)', () => {
  it('OQ-15 shows nothing without an error', () => {
    expect(problemMessages(null)).toEqual([]);
    expect(problemMessages(undefined)).toEqual([]);
  });

  it('OQ-15 shows a generic pt-BR message for an unexpected error', () => {
    expect(problemMessages(new Error('boom'))).toEqual([
      'Ocorreu um erro inesperado. Tente novamente.',
    ]);
  });

  it('OQ-15 shows every message, field-bound ones too, when no field is shown elsewhere', () => {
    const error = problem([
      { code: 'VALIDATION_ERROR', message: 'Sem campo.', field: null },
      { code: 'FUTURE_DATE', message: 'Data inválida.', field: 'start_date' },
    ]);
    expect(problemMessages(error)).toEqual(['Sem campo.', 'Data inválida.']);
  });

  it('OQ-15 falls back to the detail when the problem lists no errors', () => {
    expect(problemMessages(problem([]))).toEqual(['Detalhe']);
  });

  it('OQ-15 leaves out only the first message of each field a form shows on its input', () => {
    const error = problem([
      { code: 'VALIDATION_ERROR', message: 'Primeira de start_date.', field: 'start_date' },
      { code: 'FUTURE_DATE', message: 'Segunda de start_date.', field: 'start_date' },
      { code: 'INVALID_RANGE', message: 'De end_date.', field: 'end_date' },
      { code: 'VALIDATION_ERROR', message: 'Sem campo.', field: null },
    ]);
    expect(problemMessages(error, ['start_date'])).toEqual([
      'Segunda de start_date.',
      'De end_date.',
      'Sem campo.',
    ]);
  });
});

describe('splitProblem (forms, OQ-15)', () => {
  const error = (errors: { field: string | null; message: string }[]) =>
    problem(errors.map((e) => ({ code: 'VALIDATION_ERROR', ...e })));

  it('§12 keeps field errors on the fields the form shows, mapped to its own names', () => {
    const result = splitProblem(error([{ field: 'date', message: 'Informe a data.' }]), {
      date: 'entryDate',
    });

    expect(result).toEqual({ fields: { entryDate: 'Informe a data.' }, page: [] });
  });

  it('§12 keeps every message of a field, not only the first', () => {
    const result = splitProblem(
      error([
        { field: 'pu', message: 'Informe um número válido.' },
        { field: 'pu', message: 'Use no máximo 10 casas decimais.' },
        { field: 'source', message: 'Fonte inválida.' },
        { field: 'source', message: 'Fonte desconhecida.' },
      ]),
      sameFields(['pu']),
    );

    expect(result.fields).toEqual({
      pu: 'Informe um número válido. Use no máximo 10 casas decimais.',
    });
    expect(result.page).toEqual(['Fonte inválida.', 'Fonte desconhecida.']);
  });

  it("§12 shows on the page, in the API's order, what no input displays, so none is lost", () => {
    const result = splitProblem(
      error([
        { field: 'source', message: 'Fonte inválida.' },
        { field: null, message: 'Erro geral.' },
      ]),
      sameFields(['pu']),
    );

    expect(result.page).toEqual(['Fonte inválida.', 'Erro geral.']);
  });

  it('§12 shows a generic message for an error that is not a problem+json, and nothing for none', () => {
    expect(splitProblem(new Error('x'), {}).page).toEqual([
      'Ocorreu um erro inesperado. Tente novamente.',
    ]);
    expect(splitProblem(null, {})).toEqual({ fields: {}, page: [] });
  });
});
