-- The catalogue roots the API cannot create (no HTTP route for instrument types or asset
-- classes): FUTURE and its INTEREST_RATE_FUTURE class, the parent of the DI1 product. Idempotent:
-- running it again changes nothing. Ids come from the identity columns; callers look the roots
-- up by code (GET /api/instrument-types). `make seed` applies it to the Compose database; the DI1
-- product and its contracts are then created through the API (Ativos), as a user would.
INSERT INTO asset.instrument_types (code, name)
    SELECT 'FUTURE', 'Futuros'
    WHERE NOT EXISTS (SELECT 1 FROM asset.instrument_types WHERE code = 'FUTURE');
INSERT INTO asset.asset_classes (instrument_type_id, code, name)
    SELECT t.id, 'INTEREST_RATE_FUTURE', 'Futuros de Taxa de Juros'
    FROM asset.instrument_types AS t
    WHERE t.code = 'FUTURE'
      AND NOT EXISTS (SELECT 1 FROM asset.asset_classes WHERE code = 'INTEREST_RATE_FUTURE');
