// The helpdesk API's shapes. They come from the service's contract, generated into api-types.ts
// (npm run api-types); this file only gives the parts the client uses short names.
import type { Reply, TicketSummary } from "./api-types.ts";

export type { CloseRequest, KbArticle, NewReply, NewTicket, Reply, Ticket, TicketSummary } from "./api-types.ts";

export type TicketStatus = TicketSummary["status"];
export type Priority = TicketSummary["priority"];
export type AuthorKind = Reply["author_kind"];
