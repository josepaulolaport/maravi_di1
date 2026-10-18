import { Text, type TextProps } from '@mantine/core';

import type { Decimal } from '@/api/contract';
import { displayedSign, formatSignedMoney, UNAVAILABLE } from '@/shared/format';

interface SignedMoneyProps extends TextProps {
  value: Decimal | null | undefined;
}

/**
 * A P&L figure: explicit sign, green when positive, red when negative. The sign is always
 * written, so colour is never the only signal. `null` reads as unavailable.
 */
export function SignedMoney({ value, ...props }: SignedMoneyProps) {
  const text = formatSignedMoney(value);
  const sign = displayedSign(text);
  const colorProps = sign === 1 ? { c: 'teal.8' } : sign === -1 ? { c: 'red.7' } : {};
  const titleProps = text === UNAVAILABLE ? { title: 'Indisponível' } : {};
  return (
    <Text component="span" inherit {...colorProps} {...titleProps} {...props}>
      {text}
    </Text>
  );
}
