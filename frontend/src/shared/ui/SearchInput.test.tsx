import { act, fireEvent, screen } from '@testing-library/react';

import { renderUi } from '@/test/render';

import { SearchInput } from './SearchInput';

describe('SearchInput', () => {
  it("§11 a late URL echo of the user's own search never overwrites newer typing", () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    const { rerender } = renderUi(
      <SearchInput label="Buscar" placeholder="Buscar..." value="" onChange={onChange} />,
    );
    const box = screen.getByRole('textbox', { name: 'Buscar' });

    fireEvent.change(box, { target: { value: 'x' } });
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(onChange).toHaveBeenLastCalledWith('x');
    // The user goes on typing before the page renders the URL with "x".
    fireEvent.change(box, { target: { value: 'xy' } });
    rerender(<SearchInput label="Buscar" placeholder="Buscar..." value="x" onChange={onChange} />);

    expect(box).toHaveValue('xy');
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(onChange).toHaveBeenLastCalledWith('xy');
  });

  it('§11 a search changed from outside (Back, a link) replaces the text', () => {
    const { rerender } = renderUi(
      <SearchInput label="Buscar" placeholder="Buscar..." value="DI1" onChange={vi.fn()} />,
    );

    rerender(<SearchInput label="Buscar" placeholder="Buscar..." value="DAP" onChange={vi.fn()} />);

    expect(screen.getByRole('textbox', { name: 'Buscar' })).toHaveValue('DAP');
  });
});
