import type { IsoDate, ProcessingScope } from '@/api/contract';

import { SCOPE_URL } from '@/shared/processing/scope';
import {
  dateParam,
  enumParam,
  textParam,
  useQueryParams,
  withFallback,
} from '@/shared/url/useQueryParams';
import { useToday } from '@/shared/hooks/useToday';

// Central de Controle keeps its URL state in the query string, with the keys
// `controlCenterLinks` builds: `tab`, `inicio`, `fim`, `escopo`, plus `busca` for the search.

export type ControlCenterTab = 'pendencias' | 'processamentos';

const TABS: Record<ControlCenterTab, string> = {
  pendencias: 'pendencias',
  processamentos: 'processamentos',
};

export function useControlCenterParams() {
  const today = useToday();
  const { values, set } = useQueryParams({
    tab: withFallback(enumParam(TABS), 'pendencias'),
    // Never after today (OQ-14, OQ-29); a future date in a link is reported and dropped.
    inicio: dateParam({ max: today }),
    fim: dateParam({ max: today }),
    /** The request's scope (OQ-21): Tudo unless the URL says otherwise. */
    escopo: withFallback(enumParam(SCOPE_URL), 'ALL'),
    busca: textParam,
  });

  return {
    tab: values.tab,
    /** A new tab starts with an empty search. */
    setTab: (tab: ControlCenterTab) => {
      set({ tab, busca: null });
    },
    start: values.inicio,
    end: values.fim,
    setStart: (date: IsoDate | null) => {
      set({ inicio: date }, { push: true });
    },
    setEnd: (date: IsoDate | null) => {
      set({ fim: date }, { push: true });
    },
    scope: values.escopo,
    setScope: (scope: ProcessingScope) => {
      set({ escopo: scope });
    },
    /** Prefills the request form ("Solicitar novo processamento", OQ-20, OQ-21). */
    setRange: (start: IsoDate, end: IsoDate, scope: ProcessingScope) => {
      set({ tab: 'processamentos', inicio: start, fim: end, escopo: scope }, { push: true });
    },
    search: values.busca,
    setSearch: (text: string) => {
      set({ busca: text });
    },
    today,
  };
}

export type ControlCenterParams = ReturnType<typeof useControlCenterParams>;
