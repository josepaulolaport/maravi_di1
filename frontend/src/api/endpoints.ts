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

export const assetsApi = {
  listInstrumentTypes: () => http.get<ListResponse<InstrumentType>>('/instrument-types'),
  listProducts: (query: { instrument_type?: string; search?: string } = {}) =>
    http.get<ListResponse<Product>>('/products', { query }),
  getProduct: (productId: string) => http.get<Product>(`/products/${id(productId)}`),
  listInstruments: (query: { product_id?: string; search?: string } = {}) =>
    http.get<ListResponse<Instrument>>('/instruments', { query }),
  getInstrument: (instrumentId: string) => http.get<Instrument>(`/instruments/${id(instrumentId)}`),
  createInstrument: (body: CreateInstrumentRequest) => http.post<Instrument>('/instruments', body),
};

export const ledgerApi = {
  /** The Lançamentos list: both types, filtered and ordered by the backend (P18). */
  listEntries: (query: DateRange & { search?: string; order?: LedgerOrder }) =>
    http.get<ListResponse<LedgerEntry>>('/ledger/entries', { query }),
  createEntry: (body: CreateLedgerEntryRequest) => http.post<LedgerEntry>('/ledger/entries', body),
  /** All or nothing (§6.1); one entry is a list of one. */
  deleteEntries: (body: DeleteLedgerEntriesRequest) =>
    http.post<undefined>('/ledger/entries/deletions', body),
};

export const pricesApi = {
  listReferencePrices: (query: DateRange & { asset_id: string }) =>
    http.get<ListResponse<ReferencePriceDay>>('/reference-prices', { query }),
  setReferencePrice: (body: SetReferencePriceRequest) =>
    http.post<ReferencePrice>('/reference-prices', body),
  removeReferencePrice: (priceId: string) => http.delete(`/reference-prices/${id(priceId)}`),
};

export const portfolioApi = {
  getSummary: (date: IsoDate) =>
    http.get<PortfolioSummary>('/portfolio/summary', { query: { date } }),
  getPositions: (date: IsoDate) =>
    http.get<PortfolioPositions>('/portfolio/positions', { query: { date } }),
  getPnlSeries: (query: DateRange) => http.get<ListResponse<PnlPoint>>('/portfolio/pnl', { query }),
};

export const processingApi = {
  listRequests: () => http.get<ListResponse<ProcessingRequest>>('/processing/requests'),
  getRequest: (requestId: string) =>
    http.get<ProcessingRequest>(`/processing/requests/${id(requestId)}`),
  preview: (query: ProcessingRangeRequest) =>
    http.get<ProcessingPreview>('/processing/preview', { query: { ...query } }),
  enqueue: (body: ProcessingRangeRequest) =>
    http.post<ProcessingRequest>('/processing/requests', body),
  cancel: (requestId: string) =>
    http.post<ProcessingRequest>(`/processing/requests/${id(requestId)}/cancel`),
  cancelAndReplace: (requestId: string, body: ProcessingRangeRequest) =>
    http.post<CancelAndReplaceResponse>(
      `/processing/requests/${id(requestId)}/cancel-and-replace`,
      body,
    ),
  listIssues: () => http.get<ListResponse<Issue>>('/processing/issues'),
};
