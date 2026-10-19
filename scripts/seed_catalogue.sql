-- The catalogue the UI cannot create: the roots (no HTTP route for instrument types or asset
-- classes), FUTURE and its INTEREST_RATE_FUTURE class, and the DI1 product (Ativos only browses
-- products, spec §11.2). Idempotent: running it again changes nothing, and a DI1 product already
-- created through POST /api/products is kept as it is. Ids come from the identity columns and
-- gen_random_uuid(); every row is looked up by code. The Compose `seed` service applies it on
-- every `docker compose up`, after the migrations; `make seed` applies it again by hand. The DI1
-- contracts (instruments) are then created in the UI (Ativos → DI1 → Novo contrato).
INSERT INTO asset.instrument_types (code, name)
    SELECT 'FUTURE', 'Futuros'
    WHERE NOT EXISTS (SELECT 1 FROM asset.instrument_types WHERE code = 'FUTURE');
INSERT INTO asset.asset_classes (instrument_type_id, code, name)
    SELECT t.id, 'INTEREST_RATE_FUTURE', 'Futuros de Taxa de Juros'
    FROM asset.instrument_types AS t
    WHERE t.code = 'FUTURE'
      AND NOT EXISTS (SELECT 1 FROM asset.asset_classes WHERE code = 'INTEREST_RATE_FUTURE');
-- DI1: face value 100.000 (challenge §3); the multiplier is stored, not applied (OQ-2).
INSERT INTO asset.products (asset_class_id, code, name)
    SELECT c.id, 'DI1', 'Futuro de Depósito Interfinanceiro'
    FROM asset.asset_classes AS c
    WHERE c.code = 'INTEREST_RATE_FUTURE'
      AND NOT EXISTS (SELECT 1 FROM asset.products WHERE upper(code) = 'DI1');
INSERT INTO asset.futures (
        product_id, face_value, contract_multiplier, settlement_method, settlement_description)
    SELECT p.id, 100000, 1, 'CASH', 'Liquidação financeira'
    FROM asset.products AS p
    -- Only under FUTURE (schema.sql: a futures row needs a FUTURE product; the seed bypasses the
    -- Asset service that checks it).
    JOIN asset.asset_classes AS c ON c.id = p.asset_class_id
    JOIN asset.instrument_types AS t ON t.id = c.instrument_type_id
    WHERE upper(p.code) = 'DI1' AND t.code = 'FUTURE'
      AND NOT EXISTS (SELECT 1 FROM asset.futures WHERE product_id = p.id);
