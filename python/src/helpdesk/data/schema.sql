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

-- The approval queue (chapter 19). An agent never changes a ticket: its tools file a proposal here,
-- and a member of staff approves or rejects it. text is the reply to send, or why to close.
-- needs is whose approval it takes: 'staff' (anyone who may change the ticket) or 'lead'.
CREATE TABLE IF NOT EXISTS proposals (
  id           INTEGER PRIMARY KEY,
  kind         TEXT NOT NULL CHECK (kind IN ('reply', 'close')),
  ticket_id    INTEGER NOT NULL REFERENCES tickets(id),
  text         TEXT NOT NULL,
  agent        TEXT NOT NULL,
  proposed_for INTEGER NOT NULL REFERENCES staff(id),
  needs        TEXT NOT NULL CHECK (needs IN ('staff', 'lead')),
  status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
  decided_by   INTEGER REFERENCES staff(id),
  reason       TEXT,
  created_at   TEXT NOT NULL,
  decided_at   TEXT
);

-- Chapter 20: instruction-shaped text the agent had read, written by someone outside the company,
-- before it filed a proposal. A flag for the person deciding, never a verdict. A table of its own,
-- so a database made before chapter 20 gains it without a change to proposals.
CREATE TABLE IF NOT EXISTS proposal_flags (
  id          INTEGER PRIMARY KEY,
  proposal_id INTEGER NOT NULL REFERENCES proposals(id),
  source      TEXT NOT NULL,
  phrase      TEXT NOT NULL
);

-- Every step of the approval queue, refusals included, in the order it happened (chapter 19).
-- staff_id is the person the agent acted for when an agent filed or was refused, and the person who
-- decided otherwise. ticket_id has no foreign key: a refusal can name a ticket that doesn't exist.
CREATE TABLE IF NOT EXISTS approval_log (
  id          INTEGER PRIMARY KEY,
  at          TEXT NOT NULL,
  event       TEXT NOT NULL CHECK (event IN ('proposed', 'refused', 'approved', 'rejected')),
  proposal_id INTEGER REFERENCES proposals(id),
  ticket_id   INTEGER,
  agent       TEXT,
  staff_id    INTEGER NOT NULL REFERENCES staff(id),
  detail      TEXT NOT NULL
);
