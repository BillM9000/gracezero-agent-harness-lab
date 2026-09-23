// Generated from contracts/openapi.json by scripts/api-types.ts. Don't edit it by hand: change the
// Python models, regenerate the contract, then run npm run api-types.

export interface CloseRequest {
  staff_id: number;
}

export interface HTTPValidationError {
  detail?: ValidationError[];
}

export interface KbArticle {
  id: number;
  title: string;
  body: string;
  tags: string;
}

export interface NewReply {
  author_kind: "customer" | "staff" | "assistant";
  author_id?: number | null;
  body: string;
}

export interface NewTicket {
  customer_id: number;
  subject: string;
  body: string;
  priority?: "low" | "normal" | "high";
}

export interface Reply {
  id: number;
  ticket_id: number;
  author_kind: "customer" | "staff" | "assistant";
  author_id: number | null;
  body: string;
  created_at: string;
}

/** A single ticket, with its replies. */
export interface Ticket {
  id: number;
  customer_id: number;
  subject: string;
  body: string;
  status: "open" | "pending" | "closed";
  priority: "low" | "normal" | "high";
  assignee_id: number | null;
  created_at: string;
  closed_at: string | null;
  replies: Reply[];
}

/** A ticket as the list endpoint returns it, without its replies. */
export interface TicketSummary {
  id: number;
  customer_id: number;
  subject: string;
  body: string;
  status: "open" | "pending" | "closed";
  priority: "low" | "normal" | "high";
  assignee_id: number | null;
  created_at: string;
  closed_at: string | null;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}
