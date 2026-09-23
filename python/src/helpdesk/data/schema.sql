-- Helpdesk schema. Applied at startup; every statement is idempotent.

CREATE TABLE IF NOT EXISTS customers (
  id    INTEGER PRIMARY KEY,
  name  TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE
);

-- Human support staff. Called "staff" so it never gets confused with AI agents.
CREATE TABLE IF NOT EXISTS staff (
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('support', 'lead'))
);

CREATE TABLE IF NOT EXISTS tickets (
  id          INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  subject     TEXT NOT NULL,
  body        TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'pending', 'closed')),
  priority    TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
  assignee_id INTEGER REFERENCES staff(id),
  created_at  TEXT NOT NULL,
  closed_at   TEXT
);

CREATE TABLE IF NOT EXISTS replies (
  id          INTEGER PRIMARY KEY,
  ticket_id   INTEGER NOT NULL REFERENCES tickets(id),
  author_kind TEXT NOT NULL CHECK (author_kind IN ('customer', 'staff', 'assistant')),
  author_id   INTEGER,
  body        TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_articles (
  id    INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  body  TEXT NOT NULL,
  tags  TEXT NOT NULL DEFAULT ''
);
