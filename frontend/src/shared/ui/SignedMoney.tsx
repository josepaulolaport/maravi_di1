import type { TextProps } from '@mantine/core';

import type { Decimal } from '@/api/contract';
import { displayedSign, formatSignedMoney } from '@/shared/format';

import { Figure } from './Figure';

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
  return <Figure text={text} {...colorProps} {...props} />;
}
