import { type MantineSpacing, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconSearch } from '@tabler/icons-react';
import { useEffect, useState } from 'react';

/** How long typing must pause before the search reaches the URL (and the request or filter). */
export const SEARCH_DEBOUNCE_MS = 300;

interface SearchInputProps {
  /** The search in the URL (`?busca=`), which the screen's query or filter reads. */
  value: string;
  /** Writes the search to the URL; called once the typing has settled. */
  onChange: (value: string) => void;
  /** pt-BR accessible name, e.g. "Buscar contratos". */
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
 * settled search never overwrites such a change.
 */
export function SearchInput({ value, onChange, label, placeholder, w, maw, m }: SearchInputProps) {
  const [text, setText] = useState(value);
  const [seen, setSeen] = useState(value);
  // Whether the box holds the user's own typing (not yet in the URL, or already pushed).
  const [typing, setTyping] = useState(false);
  if (value !== seen) {
    setSeen(value);
    if (value !== text.trim()) {
      setText(value);
      setTyping(false);
    }
  }
  const [debounced] = useDebouncedValue(text, SEARCH_DEBOUNCE_MS);
  useEffect(() => {
    if (typing && debounced === text && debounced.trim() !== value) onChange(debounced.trim());
  }, [typing, debounced, text, value, onChange]);
  return (
    <TextInput
      aria-label={label}
      placeholder={placeholder}
      leftSection={<IconSearch size={16} stroke={1.5} />}
      value={text}
      onChange={(event) => {
        setText(event.currentTarget.value);
        setTyping(true);
      }}
      {...(w ? { w } : {})}
      {...(maw ? { maw } : {})}
      {...(m ? { m } : {})}
    />
  );
}
