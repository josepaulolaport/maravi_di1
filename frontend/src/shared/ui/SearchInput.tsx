import { type MantineSpacing, TextInput } from '@mantine/core';
import { useDebouncedCallback } from '@mantine/hooks';
import { IconSearch } from '@tabler/icons-react';
import { useState } from 'react';

/** How long typing must pause before the search reaches the URL (and the request or filter). */
const SEARCH_DEBOUNCE_MS = 300;

interface SearchInputProps {
  /** The search in the URL (`?busca=`), which the screen's query or filter reads. */
  value: string;
  /** Writes the search to the URL; called once the typing has settled. */
  onChange: (value: string) => void;
  /** Visible label, which is also the accessible name, e.g. "Buscar contratos". */
  label: string;
  placeholder: string;
  w?: number;
  maw?: number;
  m?: MantineSpacing;
}

/**
 * The one search box of every screen. What the user types is local, so typing is never slowed
 * by navigation; it reaches the URL only after a pause, so a request or filter runs once per
 * search, not per keystroke. A change from outside (Back, a link) replaces the text, and a
 * settled search never overwrites such a change; the page rendering the box's own earlier
 * search late (a busy machine) never overwrites newer typing.
 */
export function SearchInput({ value, onChange, label, placeholder, w, maw, m }: SearchInputProps) {
  const [text, setText] = useState(value);
  const [seen, setSeen] = useState(value);
  // The last search this box wrote: when the page renders it, it is the box's own echo.
  const [pushed, setPushed] = useState<string | null>(null);
  if (value !== seen) {
    setSeen(value);
    if (value === pushed) setPushed(null);
    else if (value !== text.trim()) setText(value);
  }
  // Runs with the latest render's state, once typing has paused.
  const push = useDebouncedCallback((search: string) => {
    // The text was replaced from outside meanwhile, or the URL already says it.
    if (search !== text.trim() || search === value) return;
    setPushed(search);
    onChange(search);
  }, SEARCH_DEBOUNCE_MS);
  return (
    <TextInput
      label={label}
      placeholder={placeholder}
      leftSection={<IconSearch size={16} stroke={1.5} />}
      value={text}
      onChange={(event) => {
        setText(event.currentTarget.value);
        push(event.currentTarget.value.trim());
      }}
      {...(w ? { w } : {})}
      {...(maw ? { maw } : {})}
      {...(m ? { m } : {})}
    />
  );
}
