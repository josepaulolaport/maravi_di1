import { useSearchParams } from 'react-router';

import type { IsoDate, ProcessingScope } from '@/api/contract';
import { isIsoDate, todayInSaoPaulo } from '@/shared/format';
import { scopeFromUrl, scopeToUrl } from '@/shared/processing/scope';
import { useFutureDateNotice } from '@/shared/ui/futureDate';

// Central de Controle keeps its URL state in the query string (frontend/CLAUDE.md), with the
// keys `controlCenterLinks` builds: `tab`, `inicio`, `fim`, `escopo`, plus `busca` for the search.

export type ControlCenterTab = 'pendencias' | 'processamentos';

const TABS: readonly ControlCenterTab[] = ['pendencias', 'processamentos'];

/** A date from the URL, or `null` when missing, invalid or after today (OQ-14, reported). */
function readDate(value: string | null, today: IsoDate): IsoDate | null {
  return isIsoDate(value) && value <= today ? value : null;
}

export function useControlCenterParams() {
  const [params, setParams] = useSearchParams();
  const today = todayInSaoPaulo();
  const requestedTab = params.get('tab');
  useFutureDateNotice([params.get('inicio'), params.get('fim')], today);
  const tab: ControlCenterTab = TABS.find((t) => t === requestedTab) ?? 'pendencias';

  const update = (changes: Record<string, string | null>) => {
    setParams(
      (current) => {
        for (const [key, value] of Object.entries(changes)) {
          if (value) current.set(key, value);
          else current.delete(key);
        }
        return current;
      },
      { replace: true },
    );
  };

  return {
    tab,
    /** A new tab starts with an empty search. */
    setTab: (next: ControlCenterTab) => {
      update({ tab: next, busca: null });
    },
    start: readDate(params.get('inicio'), today),
    end: readDate(params.get('fim'), today),
    setStart: (date: IsoDate | null) => {
      update({ inicio: date });
    },
    setEnd: (date: IsoDate | null) => {
      update({ fim: date });
    },
    /** The request's scope (OQ-21): Tudo unless the URL says otherwise. */
    scope: scopeFromUrl(params.get('escopo')) ?? 'ALL',
    setScope: (scope: ProcessingScope) => {
      update({ escopo: scopeToUrl(scope) });
    },
    /** Prefills the request form ("Solicitar novo processamento", OQ-20, OQ-21). */
    setRange: (start: IsoDate, end: IsoDate, scope: ProcessingScope) => {
      update({ tab: 'processamentos', inicio: start, fim: end, escopo: scopeToUrl(scope) });
    },
    search: params.get('busca') ?? '',
    setSearch: (text: string) => {
      update({ busca: text });
    },
    today,
  };
}
