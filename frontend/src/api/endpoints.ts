import type {
  CancelAndReplaceResponse,
  CreateInstrumentRequest,
  CreateLedgerEntryRequest,
  DeleteLedgerEntriesRequest,
  LedgerEntry,
  LedgerOrder,
  Instrument,
  InstrumentType,
  IsoDate,
  Issue,
  ListResponse,
  Page,
  PageQuery,
  PnlPoint,
  PortfolioPositions,
  PortfolioSummary,
  ProcessingPreview,
  ProcessingRangeRequest,
  ProcessingRequest,
  Product,
  ReferencePrice,
  ReferencePriceDay,
  SetReferencePriceRequest,
} from './contract';
import { http } from './http';

// One typed function per endpoint (docs/interfaces.md "HTTP endpoints" plus the proposals in
// ./contract). Feature hooks call these; nothing else builds URLs.

// A type alias (not an interface) so it is assignable to the client's query record.
type DateRange = { start_date: IsoDate; end_date: IsoDate };

const id = (value: string) => encodeURIComponent(value);

/** Reads take TanStack Query's abort signal, so a superseded request is cancelled. */
const abortable = (signal?: AbortSignal) => (signal ? { signal } : {});

export const assetsApi = {
  listInstrumentTypes: (signal?: AbortSignal) =>
    http.get<ListResponse<InstrumentType>>('/instrument-types', abortable(signal)),
  listProducts: (query: { instrument_type?: string; search?: string } = {}, signal?: AbortSignal) =>
    http.get<ListResponse<Product>>('/products', { query, ...abortable(signal) }),
  getProduct: (productId: string, signal?: AbortSignal) =>
    http.get<Product>(`/products/${id(productId)}`, abortable(signal)),
  listInstruments: (query: { product_id?: string; search?: string } = {}, signal?: AbortSignal) =>
    http.get<ListResponse<Instrument>>('/instruments', { query, ...abortable(signal) }),
  getInstrument: (instrumentId: string, signal?: AbortSignal) =>
    http.get<Instrument>(`/instruments/${id(instrumentId)}`, abortable(signal)),
  createInstrument: (body: CreateInstrumentRequest) => http.post<Instrument>('/instruments', body),
};

export const ledgerApi = {
  /** The Lançamentos list: both types, filtered and ordered by the backend (P18). */
  listEntries: (
    query: DateRange & PageQuery & { search?: string; order?: LedgerOrder },
    signal?: AbortSignal,
  ) => http.get<Page<LedgerEntry>>('/ledger/entries', { query, ...abortable(signal) }),
  createEntry: (body: CreateLedgerEntryRequest) => http.post<LedgerEntry>('/ledger/entries', body),
  /** All or nothing (§6.1); one entry is a list of one. */
  deleteEntries: (body: DeleteLedgerEntriesRequest) =>
    http.post<undefined>('/ledger/entries/deletions', body),
};

export const pricesApi = {
  listReferencePrices: (query: DateRange & { asset_id: string }, signal?: AbortSignal) =>
    http.get<ListResponse<ReferencePriceDay>>('/reference-prices', {
      query,
      ...abortable(signal),
    }),
  setReferencePrice: (body: SetReferencePriceRequest) =>
    http.post<ReferencePrice>('/reference-prices', body),
  removeReferencePrice: (priceId: string) => http.delete(`/reference-prices/${id(priceId)}`),
};

export const portfolioApi = {
  getSummary: (date: IsoDate, signal?: AbortSignal) =>
    http.get<PortfolioSummary>('/portfolio/summary', { query: { date }, ...abortable(signal) }),
  getPositions: (date: IsoDate, signal?: AbortSignal) =>
    http.get<PortfolioPositions>('/portfolio/positions', {
      query: { date },
      ...abortable(signal),
    }),
  getPnlSeries: (query: DateRange, signal?: AbortSignal) =>
    http.get<ListResponse<PnlPoint>>('/portfolio/pnl', { query, ...abortable(signal) }),
};

export const processingApi = {
  /** Newest first, by (created_at, id). */
  listRequests: (query: PageQuery = {}, signal?: AbortSignal) =>
    http.get<Page<ProcessingRequest>>('/processing/requests', {
      query: { ...query },
      ...abortable(signal),
    }),
  getRequest: (requestId: string) =>
    http.get<ProcessingRequest>(`/processing/requests/${id(requestId)}`),
  preview: (query: ProcessingRangeRequest, signal?: AbortSignal) =>
    http.get<ProcessingPreview>('/processing/preview', {
      query: { ...query },
      ...abortable(signal),
    }),
  enqueue: (body: ProcessingRangeRequest) =>
    http.post<ProcessingRequest>('/processing/requests', body),
  cancel: (requestId: string) =>
    http.post<ProcessingRequest>(`/processing/requests/${id(requestId)}/cancel`),
  cancelAndReplace: (requestId: string, body: ProcessingRangeRequest) =>
    http.post<CancelAndReplaceResponse>(
      `/processing/requests/${id(requestId)}/cancel-and-replace`,
      body,
    ),
  listIssues: (signal?: AbortSignal) =>
    http.get<ListResponse<Issue>>('/processing/issues', abortable(signal)),
};
