import { describe, expect, it } from "vitest";

import { run, USAGE } from "../src/cli.ts";
import { type Fetch, HelpdeskClient, HelpdeskError } from "../src/client.ts";

interface Call {
  url: string;
  init: RequestInit | undefined;
}

/** A fake fetch that records every call and answers with one canned response. */
function fakeFetch(status: number, body: unknown): { fetch: Fetch; calls: Call[] } {
  const calls: Call[] = [];
  const fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as Fetch;
  return { fetch, calls };
}

const ticket = {
  id: 1,
  customer_id: 1,
  subject: "Cannot reset my password",
  body: "The reset email never arrives.",
  status: "open",
  priority: "high",
  assignee_id: null,
  created_at: "2026-09-01T09:00:00+00:00",
  closed_at: null,
};

describe("HelpdeskClient", () => {
  it("lists tickets by status and trims a trailing slash from the base URL", async () => {
    const { fetch, calls } = fakeFetch(200, [ticket]);
    const tickets = await new HelpdeskClient("http://helpdesk.test/", fetch).listTickets("open");
    expect(calls[0]?.url).toBe("http://helpdesk.test/tickets?status=open");
    expect(tickets[0]?.subject).toBe("Cannot reset my password");
  });

  it("posts a new ticket as JSON", async () => {
    const { fetch, calls } = fakeFetch(201, ticket);
    await new HelpdeskClient("http://helpdesk.test", fetch).createTicket({
      customer_id: 1,
      subject: "Hi",
      body: "Hello",
    });
    expect(calls[0]?.init?.method).toBe("POST");
    expect(calls[0]?.init?.headers).toEqual({ "content-type": "application/json" });
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ customer_id: 1, subject: "Hi", body: "Hello" });
  });

  it("turns a service error into a HelpdeskError with the service's own message", async () => {
    const { fetch } = fakeFetch(404, { error: "ticket 999 does not exist" });
    const failure = new HelpdeskClient("http://helpdesk.test", fetch).getTicket(999);
    await expect(failure).rejects.toThrow(HelpdeskError);
    await expect(failure).rejects.toMatchObject({ status: 404, message: "ticket 999 does not exist" });
  });

  it("makes request-validation errors readable", async () => {
    const { fetch } = fakeFetch(422, {
      detail: [{ loc: ["body", "subject"], msg: "String should have at least 1 character" }],
    });
    const failure = new HelpdeskClient("http://helpdesk.test", fetch).createTicket({
      customer_id: 1,
      subject: "",
      body: "x",
    });
    await expect(failure).rejects.toMatchObject({
      status: 422,
      message: "body.subject: String should have at least 1 character",
    });
  });
});

describe("cli", () => {
  function client(fetch: Fetch): HelpdeskClient {
    return new HelpdeskClient("http://helpdesk.test", fetch);
  }

  it("prints one line per ticket", async () => {
    const lines: string[] = [];
    const code = await run(["tickets", "open"], client(fakeFetch(200, [ticket]).fetch), (l) => lines.push(l));
    expect(code).toBe(0);
    expect(lines).toEqual(["#1 [open] Cannot reset my password"]);
  });

  it("rejects an unknown status before calling the service", async () => {
    const { fetch, calls } = fakeFetch(200, []);
    const lines: string[] = [];
    const code = await run(["tickets", "archived"], client(fetch), (l) => lines.push(l));
    expect(code).toBe(2);
    expect(calls).toHaveLength(0);
    expect(lines[0]).toContain('unknown status "archived"');
  });

  it("reports a service error with its status and exits 1", async () => {
    const lines: string[] = [];
    const failing = fakeFetch(404, { error: "ticket 999 does not exist" }).fetch;
    const code = await run(["ticket", "999"], client(failing), (l) => lines.push(l));
    expect(code).toBe(1);
    expect(lines).toEqual(["error 404: ticket 999 does not exist"]);
  });

  it("prints usage for an unknown command", async () => {
    const lines: string[] = [];
    const code = await run(["frobnicate"], client(fakeFetch(200, []).fetch), (l) => lines.push(l));
    expect(code).toBe(2);
    expect(lines).toEqual([USAGE]);
  });
});
