import type { AuthorKind, CloseRequest, KbArticle, NewReply, NewTicket, Ticket, TicketStatus, TicketSummary } from "./types.ts";

export type Fetch = typeof fetch;

/** An error the helpdesk returned, carrying its HTTP status and its own readable message. */
export class HelpdeskError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "HelpdeskError";
    this.status = status;
  }
}

/** Service errors arrive as {"error": "..."}; request validation errors as {"detail": [...]}. */
function errorMessage(status: number, payload: unknown): string {
  if (typeof payload === "object" && payload !== null) {
    if ("error" in payload && typeof payload.error === "string") return payload.error;
    if ("detail" in payload && Array.isArray(payload.detail)) {
      return payload.detail
        .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).join(".")}: ${d.msg ?? "invalid"}`)
        .join("; ");
    }
  }
  return `HTTP ${status}`;
}

export class HelpdeskClient {
  readonly #baseUrl: string;
  readonly #fetch: Fetch;

  /** fetchImpl lets tests pass a fake; everything else uses the real fetch. */
  constructor(baseUrl: string, fetchImpl: Fetch = fetch) {
    this.#baseUrl = baseUrl.replace(/\/+$/, "");
    this.#fetch = fetchImpl;
  }

  async #request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    const init: RequestInit = { method };
    if (body !== undefined) {
      init.headers = { "content-type": "application/json" };
      init.body = JSON.stringify(body);
    }
    const response = await this.#fetch(`${this.#baseUrl}${path}`, init);
    const payload: unknown = await response.json();
    if (!response.ok) throw new HelpdeskError(response.status, errorMessage(response.status, payload));
    return payload as T;
  }

  listTickets(status?: TicketStatus): Promise<TicketSummary[]> {
    const query = status === undefined ? "" : `?status=${encodeURIComponent(status)}`;
    return this.#request("GET", `/tickets${query}`);
  }

  getTicket(id: number): Promise<Ticket> {
    return this.#request("GET", `/tickets/${id}`);
  }

  createTicket(ticket: NewTicket): Promise<Ticket> {
    return this.#request("POST", "/tickets", ticket);
  }

  addReply(id: number, authorKind: AuthorKind, body: string, authorId?: number): Promise<Ticket> {
    const reply: NewReply = { author_kind: authorKind, author_id: authorId ?? null, body };
    return this.#request("POST", `/tickets/${id}/replies`, reply);
  }

  closeTicket(id: number, staffId: number): Promise<Ticket> {
    const request: CloseRequest = { staff_id: staffId };
    return this.#request("POST", `/tickets/${id}/close`, request);
  }

  searchKb(query: string, limit = 5): Promise<KbArticle[]> {
    return this.#request("GET", `/kb/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  }
}
