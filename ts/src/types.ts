// Shapes returned by the helpdesk API. They mirror the Python service's JSON exactly.

export type TicketStatus = "open" | "pending" | "closed";
export type Priority = "low" | "normal" | "high";
export type AuthorKind = "customer" | "staff" | "assistant";

export interface Reply {
  id: number;
  ticket_id: number;
  author_kind: AuthorKind;
  author_id: number | null;
  body: string;
  created_at: string;
}

export interface Ticket {
  id: number;
  customer_id: number;
  subject: string;
  body: string;
  status: TicketStatus;
  priority: Priority;
  assignee_id: number | null;
  created_at: string;
  closed_at: string | null;
  replies?: Reply[];
}

export interface KbArticle {
  id: number;
  title: string;
  body: string;
  tags: string;
}

export interface NewTicket {
  customer_id: number;
  subject: string;
  body: string;
  priority?: Priority;
}
