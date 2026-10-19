import type { FieldError } from '@/api/contract';
import { ApiError } from '@/api/http';

import { problemMessages } from './problemMessages';

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
