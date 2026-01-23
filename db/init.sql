CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS org (
  org_key text PRIMARY KEY,
  name_ru text NOT NULL,
  address text NOT NULL,
  a0 text,
  a1 text,
  rub text[] NOT NULL
);

CREATE TABLE IF NOT EXISTS rev (
  rev_id text PRIMARY KEY,
  org_key text NOT NULL REFERENCES org(org_key),
  rating smallint NOT NULL CHECK (rating >= 0 AND rating <= 5),
  text text NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('russian', coalesce(text,''))) STORED
);

CREATE INDEX IF NOT EXISTS org_rub_gin ON org USING gin (rub);
CREATE INDEX IF NOT EXISTS org_a0_idx ON org (a0);
CREATE INDEX IF NOT EXISTS org_a1_idx ON org (a1);
CREATE INDEX IF NOT EXISTS rev_org_idx ON rev (org_key);
CREATE INDEX IF NOT EXISTS rev_rating_idx ON rev (rating);
CREATE INDEX IF NOT EXISTS rev_tsv_gin ON rev USING gin (tsv);

CREATE INDEX IF NOT EXISTS org_name_trgm ON org USING gin (name_ru gin_trgm_ops);
CREATE INDEX IF NOT EXISTS org_addr_trgm ON org USING gin (address gin_trgm_ops);
