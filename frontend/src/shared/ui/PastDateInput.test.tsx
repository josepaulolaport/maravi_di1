import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import type { IsoDate } from '@/api/contract';
import { renderUi } from '@/test/render';

import { PastDateInput } from './PastDateInput';

function Harness({
  maxDate,
  limitMessage,
  onSubmit,
}: {
  maxDate: IsoDate;
  limitMessage?: string;
  onSubmit: (date: IsoDate | null) => void;
}) {
  const [date, setDate] = useState<IsoDate | null>('2026-09-10');
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(date);
      }}
    >
      <PastDateInput
        label="Data"
        today="2026-10-18"
        maxDate={maxDate}
        limitMessage={limitMessage}
        value={date}
        onChange={setDate}
      />
    </form>
  );
}

describe('PastDateInput', () => {
  it('OQ-14 refuses a future date typed and submitted with Enter: the old date never goes out', async () => {
    const submitted: (IsoDate | null)[] = [];
    renderUi(<Harness maxDate="2026-10-18" onSubmit={(d) => submitted.push(d)} />);
    const user = userEvent.setup();
    const input = screen.getByRole('textbox', { name: 'Data' });

    await user.clear(input);
    await user.type(input, '19/10/2026{enter}');

    expect(await screen.findByText('A data não pode ser posterior a hoje.')).toBeInTheDocument();
    expect(submitted.every((d) => d !== '2026-09-10')).toBe(true);
  });

  it('OQ-1 refuses a typed date after a past maturity with its own message', async () => {
    renderUi(
      <Harness
        maxDate="2026-09-20"
        limitMessage="O contrato já venceu nesta data."
        onSubmit={() => undefined}
      />,
    );
    const user = userEvent.setup();
    const input = screen.getByRole('textbox', { name: 'Data' });

    await user.clear(input);
    await user.type(input, '25/09/2026');
    await user.tab();

    expect(await screen.findByText('O contrato já venceu nesta data.')).toBeInTheDocument();
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).not.toHaveValue('10/09/2026');
  });

  it('accepts a date up to the limit', async () => {
    renderUi(<Harness maxDate="2026-10-18" onSubmit={() => undefined} />);
    const user = userEvent.setup();
    const input = screen.getByRole('textbox', { name: 'Data' });

    await user.clear(input);
    await user.type(input, '18/10/2026');
    await user.tab();

    expect(input).toHaveValue('18/10/2026');
    expect(input).not.toHaveAttribute('aria-invalid', 'true');
  });
});
