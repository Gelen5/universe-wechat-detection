-- Future payment/report persistence schema.
-- The first beta keeps reports in the response; this schema is ready for
-- payment, history, retry and refund flows without changing the API shape.

CREATE TABLE IF NOT EXISTS diagnosis_orders (
  id TEXT PRIMARY KEY,
  account_name TEXT NOT NULL,
  amount_cents INTEGER NOT NULL DEFAULT 590,
  payment_status TEXT NOT NULL DEFAULT 'unpaid',
  diagnosis_status TEXT NOT NULL DEFAULT 'pending',
  report_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  paid_at TEXT,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_diagnosis_orders_account_name
  ON diagnosis_orders(account_name);
