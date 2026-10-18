import type {
  CancelAndReplaceResponse,
  CashMovement,
  CreateCashMovementRequest,
  CreateInstrumentRequest,
  CreateTradeRequest,
  DeleteEntriesRequest,
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
  Trade,
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
  listTrades: (query: DateRange & { search?: string }) =>
    http.get<ListResponse<Trade>>('/trades', { query }),
  createTrade: (body: CreateTradeRequest) => http.post<Trade>('/trades', body),
  deleteTrade: (tradeId: string) => http.delete(`/trades/${id(tradeId)}`),
  listCashMovements: (query: DateRange & { search?: string }) =>
    http.get<ListResponse<CashMovement>>('/cash-movements', { query }),
  createCashMovement: (body: CreateCashMovementRequest) =>
    http.post<CashMovement>('/cash-movements', body),
  deleteCashMovement: (movementId: string) => http.delete(`/cash-movements/${id(movementId)}`),
  deleteEntries: (body: DeleteEntriesRequest) => http.post<undefined>('/ledger/deletions', body),
};

export const pricesApi = {
  listReferencePrices: (query: DateRange & { asset_id: string }) =>
    http.get<ListResponse<ReferencePriceDay>>('/reference-prices', { query }),
  listRevisions: (query: { asset_id: string; reference_date: IsoDate }) =>
    http.get<ListResponse<ReferencePrice>>('/reference-prices/revisions', { query }),
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
