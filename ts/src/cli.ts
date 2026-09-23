// A small command-line tool for the helpdesk API.
// Usage: node src/cli.ts [--url http://127.0.0.1:8000] <command> [args]

import { fileURLToPath } from "node:url";

import { HelpdeskClient, HelpdeskError } from "./client.ts";
import type { TicketStatus } from "./types.ts";

export const USAGE = `usage: node src/cli.ts [--url <base-url>] <command>

commands:
  tickets [open|pending|closed]   list tickets, optionally by status
  ticket <id>                     show one ticket with its replies
  kb <query>                      search the knowledge base`;

type Client = Pick<HelpdeskClient, "listTickets" | "getTicket" | "searchKb">;
const STATUSES: readonly string[] = ["open", "pending", "closed"];

/** Runs one command and returns the process exit code. Output goes through `write` so tests can read it. */
export async function run(args: string[], client: Client, write: (line: string) => void): Promise<number> {
  const [command, arg] = args;
  try {
    if (command === "tickets") {
      if (arg !== undefined && !STATUSES.includes(arg)) {
        write(`unknown status "${arg}"; use one of ${STATUSES.join(", ")}`);
        return 2;
      }
      for (const t of await client.listTickets(arg as TicketStatus | undefined)) {
        write(`#${t.id} [${t.status}] ${t.subject}`);
      }
      return 0;
    }
    if (command === "ticket" && arg !== undefined && /^\d+$/.test(arg)) {
      const t = await client.getTicket(Number(arg));
      write(`#${t.id} [${t.status}] ${t.subject}`);
      write(t.body);
      for (const r of t.replies) write(`  ${r.author_kind}: ${r.body}`);
      return 0;
    }
    if (command === "kb" && arg !== undefined) {
      for (const a of await client.searchKb(args.slice(1).join(" "))) write(`${a.title}: ${a.body}`);
      return 0;
    }
    write(USAGE);
    return 2;
  } catch (err) {
    if (err instanceof HelpdeskError) {
      write(`error ${err.status}: ${err.message}`);
      return 1;
    }
    throw err;
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const argv = process.argv.slice(2);
  let baseUrl = process.env.HELPDESK_URL ?? "http://127.0.0.1:8000";
  if (argv[0] === "--url" && argv[1] !== undefined) {
    baseUrl = argv[1];
    argv.splice(0, 2);
  }
  process.exitCode = await run(argv, new HelpdeskClient(baseUrl), (line) => console.log(line));
}
