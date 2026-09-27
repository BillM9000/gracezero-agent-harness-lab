// Every request the client makes must match a route in the service's contract: the path, the
// method, the query parameters and the fields of the body. The contract is generated from the
// Python code (chapter 7), so this is how the client finds out the service changed.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { type Fetch, HelpdeskClient } from "../src/client.ts";

interface Operation {
  parameters?: { name: string; in: string }[];
  requestBody?: { content: Record<string, { schema: { $ref: string } }> };
}
interface Contract {
  paths: Record<string, Record<string, Operation>>;
  components: { schemas: Record<string, { properties?: Record<string, unknown>; required?: string[] }> };
}

const contract = JSON.parse(readFileSync(new URL("../../contracts/openapi.json", import.meta.url), "utf8")) as Contract;

interface Sent {
  method: string;
  url: URL;
  body: Record<string, unknown> | undefined;
}

// A client whose requests are recorded rather than sent.
function recordingClient(): { client: HelpdeskClient; sent: Sent[] } {
  const sent: Sent[] = [];
  const fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : undefined;
    sent.push({ method: init?.method ?? "GET", url: new URL(String(url)), body });
    return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
  }) as Fetch;
  return { client: new HelpdeskClient("http://helpdesk.test", fetch), sent };
}

// The contract's operation for a request, or a sentence saying why there isn't one.
function operationFor(request: Sent): Operation | string {
  for (const [template, item] of Object.entries(contract.paths)) {
    const pattern = new RegExp(`^${template.replace(/\{[^}]+\}/g, "[^/]+")}$`);
    if (!pattern.test(request.url.pathname)) continue;
    return item[request.method.toLowerCase()] ?? `${request.method} isn't allowed on ${template}`;
  }
  return `no route matches ${request.url.pathname}`;
}

// One call of every method the client has. The last test fails when the client gains a method
// this doesn't call, so no request goes unchecked against the contract.
async function callEveryMethod(client: HelpdeskClient): Promise<void> {
  await client.listTickets("open");
  await client.getTicket(1);
  await client.createTicket({ customer_id: 1, subject: "Help", body: "It broke." });
  await client.addReply(1, "staff", "On it.", 2);
  await client.closeTicket(1, 2);
  await client.searchKb("password", 3);
}

describe("the client against the contract", () => {
  it("sends only requests the contract describes, with the fields it expects", async () => {
    const { client, sent } = recordingClient();
    await callEveryMethod(client);
    expect(sent).toHaveLength(6);

    for (const request of sent) {
      const call = `${request.method} ${request.url.pathname}${request.url.search}`;
      const operation = operationFor(request);
      expect(typeof operation === "string" ? `${call}: ${operation}` : "matched").toBe("matched");
      if (typeof operation === "string") continue;

      const queryNames = new Set((operation.parameters ?? []).filter((p) => p.in === "query").map((p) => p.name));
      for (const name of request.url.searchParams.keys()) {
        expect(queryNames.has(name) ? "known" : `${call}: the contract has no query parameter "${name}"`).toBe("known");
      }

      const ref = operation.requestBody?.content["application/json"]?.schema.$ref;
      if (request.body === undefined || ref === undefined) {
        expect(`${request.body !== undefined}`, `${call}: body sent ${request.body !== undefined}, body expected ${ref !== undefined}`).toBe(`${ref !== undefined}`);
        continue;
      }
      const schema = contract.components.schemas[ref.split("/").at(-1) ?? ""];
      const fields = new Set(Object.keys(schema?.properties ?? {}));
      for (const key of Object.keys(request.body)) {
        expect(fields.has(key) ? "known" : `${call}: the contract has no body field "${key}"`).toBe("known");
      }
      for (const key of schema?.required ?? []) {
        expect(key in request.body ? "sent" : `${call}: the required body field "${key}" is missing`).toBe("sent");
      }
    }
  });

  it("calls every method the client has", async () => {
    const { client } = recordingClient();
    const called = new Set<string>();
    const watched = new Proxy(client, {
      get(target, name, receiver) {
        const value: unknown = Reflect.get(target, name, receiver);
        if (typeof value !== "function") return value;
        called.add(String(name));
        return (value as (...args: unknown[]) => unknown).bind(target);
      },
    });
    await callEveryMethod(watched);
    const methods = Object.getOwnPropertyNames(HelpdeskClient.prototype).filter((name) => name !== "constructor");
    expect(methods.length).toBeGreaterThan(0);
    const uncalled = methods.filter((name) => !called.has(name));
    expect(uncalled, `callEveryMethod doesn't call ${uncalled.join(", ")}: add a call, so its request is checked against the contract`).toEqual([]);
  });
});
