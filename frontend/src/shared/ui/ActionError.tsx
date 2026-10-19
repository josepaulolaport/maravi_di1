import { MessageAlert } from './MessageAlert';
import { problemMessages } from './problemMessages';

/**
 * A failed action in a modal (OQ-15): its problem+json messages (`problemMessages`), except
 * those bound to a field in `shownOnFields`, which the form shows on its own inputs.
 */
export function ActionError({
  error,
  shownOnFields = [],
}: {
  error: unknown;
  shownOnFields?: readonly string[];
}) {
  return <MessageAlert messages={problemMessages(error, shownOnFields)} />;
}
