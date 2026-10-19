import { matchPath } from 'react-router';

import { IDS } from '@/test/msw/fixtures';

import { assetLinks, controlCenterLinks, ledgerLinks, paths } from './paths';

describe('paths and deep links', () => {
  it('§11.2 links the Ativos catalogue, a product and a contract', () => {
    expect(assetLinks.catalogue()).toBe('/ativos');
    expect(assetLinks.product(IDS.di1)).toBe(`/ativos/produtos/${IDS.di1}`);
    expect(assetLinks.contract(IDS.di1f28)).toBe(`/ativos/contratos/${IDS.di1f28}`);
  });

  it('§11.1 "Definir preço" opens the contract page with the price modal on the missing date', () => {
    expect(assetLinks.contract(IDS.di1f29, { register: '2026-10-16' })).toBe(
      `/ativos/contratos/${IDS.di1f29}?registrar=2026-10-16`,
    );
  });

  it('§11.2 route patterns match the links', () => {
    expect(paths.assetProduct).toBe('/ativos/produtos/:productId');
    expect(paths.assetContract).toBe('/ativos/contratos/:instrumentId');
    expect(matchPath(paths.assetProduct, assetLinks.product(IDS.di1))?.params).toEqual({
      productId: IDS.di1,
    });
    expect(matchPath(paths.assetContract, assetLinks.contract('a/b'))?.params).toEqual({
      instrumentId: 'a/b',
    });
  });

  it('§11.1 links the Central de Controle tabs, with an optional prefilled range', () => {
    expect(controlCenterLinks.issues()).toBe('/central-de-controle?tab=pendencias');
    expect(controlCenterLinks.processing()).toBe('/central-de-controle?tab=processamentos');
    expect(controlCenterLinks.processing({ start: '2026-10-14', end: '2026-10-16' })).toBe(
      '/central-de-controle?tab=processamentos&inicio=2026-10-14&fim=2026-10-16',
    );
  });

  it('§10.3 "Processar intervalo anterior" can prefill the end date alone', () => {
    expect(controlCenterLinks.processing({ end: '2026-10-15' })).toBe(
      '/central-de-controle?tab=processamentos&fim=2026-10-15',
    );
  });

  it('§11.3 links Lançamentos with an inclusive range and a search', () => {
    expect(ledgerLinks.list()).toBe('/lancamentos');
    expect(ledgerLinks.list({ search: 'DI1F28' })).toBe('/lancamentos?busca=DI1F28');
    expect(ledgerLinks.list({ start: '2026-09-19', end: '2026-10-18', search: 'DI1 F28' })).toBe(
      '/lancamentos?inicio=2026-09-19&fim=2026-10-18&busca=DI1+F28',
    );
  });
});
