import { useRef } from 'react';

/**
 * Runs one submission at a time. A double click reaches the handler twice before the pending
 * state is rendered; the second call is ignored until the first one settles, so one click never
 * queues two jobs or saves two entries (§10.2). The submission's own handlers show its outcome;
 * a rejection is not rethrown.
 */
export function useSubmitOnce() {
  const running = useRef(false);
  return (submit: () => Promise<unknown> | undefined) => {
    if (running.current) return;
    const attempt = submit();
    if (attempt === undefined) return;
    running.current = true;
    void attempt
      .catch(() => undefined)
      .finally(() => {
        running.current = false;
      });
  };
}
