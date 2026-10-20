import { useForm, type UseFormInput } from '@mantine/form';
import { useState } from 'react';

import { splitProblem } from '@/shared/ui/problemMessages';

import { useSubmitOnce } from './useSubmitOnce';

/**
 * A Mantine form whose save goes to the API. A failed save is split as OQ-15 says: each message
 * whose API field is in `fieldMap` goes on that input (editing it clears it), the rest above the
 * form (`pageErrors`). The save runs once per submission (`useSubmitOnce`).
 */
export function useApiForm<Values extends Record<string, unknown>>(
  input: UseFormInput<Values>,
  /** API field (`errors[].field`) → the form field that shows its messages. */
  fieldMap: Readonly<Record<string, keyof Values & string>>,
) {
  const form = useForm<Values>(input);
  const [pageErrors, setPageErrors] = useState<string[]>([]);
  const once = useSubmitOnce();

  const showError = (error: unknown) => {
    const { fields, page } = splitProblem(error, fieldMap);
    form.setErrors(fields);
    setPageErrors(page);
  };

  return {
    form,
    /** Messages of the last failed save that no input shows. */
    pageErrors,
    clearPageErrors: () => {
      setPageErrors([]);
    },
    /**
     * The form's `onSubmit`: validates, then runs `save` once. `save` returns the request's
     * promise (`mutateAsync(...).then(...)`), or nothing when there is nothing to send.
     */
    onSubmit: (save: (values: Values) => Promise<unknown> | undefined) =>
      form.onSubmit((values) => {
        once(() => {
          setPageErrors([]);
          return save(values)?.catch(showError);
        });
      }),
  };
}
