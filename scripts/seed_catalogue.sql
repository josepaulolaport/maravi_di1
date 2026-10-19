-- The catalogue roots the API cannot create (no HTTP route for instrument types or asset
-- classes): FUTURE and its INTEREST_RATE_FUTURE class, the parent of the DI1 product. Idempotent:
-- running it again changes nothing. `make seed` applies it to the Compose database; the DI1
-- product and its contracts are then created through the API (Ativos), as a user would.
INSERT INTO asset.instrument_types (id, code, name)
    VALUES (1, 'FUTURE', 'Futuros')
    ON CONFLICT DO NOTHING;
INSERT INTO asset.asset_classes (id, instrument_type_id, code, name)
    VALUES (1, 1, 'INTEREST_RATE_FUTURE', 'Futuros de Taxa de Juros')
    ON CONFLICT DO NOTHING;
