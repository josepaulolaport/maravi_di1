import type { FieldError } from '@/api/contract';
import { ApiError } from '@/api/http';

import { problemMessages, splitProblem } from './problemMessages';

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

  it('OQ-15 shows the first message of a field on its input and the rest above the form', () => {
    const result = splitProblem(
      error([
        { field: 'pu', message: 'Informe um número válido.' },
        { field: 'pu', message: 'Use no máximo 10 casas decimais.' },
        { field: 'source', message: 'Fonte inválida.' },
        { field: 'source', message: 'Fonte desconhecida.' },
      ]),
      { pu: 'pu' },
    );

    expect(result.fields).toEqual({ pu: 'Informe um número válido.' });
    expect(result.page).toEqual([
      'Use no máximo 10 casas decimais.',
      'Fonte inválida.',
      'Fonte desconhecida.',
    ]);
  });

  it('OQ-15 leaves out only the first message of each field a form shows on its input', () => {
    const result = splitProblem(
      error([
        { field: 'start_date', message: 'Primeira de start_date.' },
        { field: 'start_date', message: 'Segunda de start_date.' },
        { field: 'end_date', message: 'De end_date.' },
        { field: null, message: 'Sem campo.' },
      ]),
      { start_date: 'start' },
    );

    expect(result.fields).toEqual({ start: 'Primeira de start_date.' });
    expect(result.page).toEqual(['Segunda de start_date.', 'De end_date.', 'Sem campo.']);
  });

  it("§12 shows on the page, in the API's order, what no input displays, so none is lost", () => {
    const result = splitProblem(
      error([
        { field: 'source', message: 'Fonte inválida.' },
        { field: null, message: 'Erro geral.' },
      ]),
      { pu: 'pu' },
    );

    expect(result.page).toEqual(['Fonte inválida.', 'Erro geral.']);
  });

  it("§12 shows the problem's own message when it lists no errors", () => {
    expect(splitProblem(problem([]), {})).toEqual({ fields: {}, page: ['Detalhe'] });
  });

  it('§12 shows a generic message for an error that is not a problem+json, and nothing for none', () => {
    expect(splitProblem(new Error('x'), {}).page).toEqual([
      'Ocorreu um erro inesperado. Tente novamente.',
    ]);
    expect(splitProblem(null, {})).toEqual({ fields: {}, page: [] });
  });
  it('OQ-15 maps only the fields the form owns, never an inherited name', () => {
    const result = splitProblem(error([{ field: 'constructor', message: 'Campo estranho.' }]), {});
    expect(result).toEqual({ fields: {}, page: ['Campo estranho.'] });
  });
});
