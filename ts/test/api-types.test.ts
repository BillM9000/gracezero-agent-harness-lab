import { describe, expect, it } from "vitest";

import { generate, type Schema, typeFor } from "../scripts/openapi-to-ts.ts";

describe("openapi-to-ts", () => {
  it("writes an interface per object schema, with optional fields marked", () => {
    const text = generate({
      components: {
        schemas: {
          Note: {
            type: "object",
            description: "A note.",
            required: ["id"],
            properties: { id: { type: "integer" }, text: { type: "string" } },
          },
        },
      },
    });
    expect(text).toContain("/** A note. */\nexport interface Note {\n  id: number;\n  text?: string;\n}");
    expect(text.startsWith("// Generated from contracts/openapi.json")).toBe(true);
  });

  it("turns enums, nullable values, arrays and references into their TypeScript forms", () => {
    expect(typeFor({ type: "string", enum: ["open", "closed"] }, "x")).toBe('"open" | "closed"');
    expect(typeFor({ anyOf: [{ type: "integer" }, { type: "null" }] }, "x")).toBe("number | null");
    expect(typeFor({ type: "array", items: { $ref: "#/components/schemas/Reply" } }, "x")).toBe("Reply[]");
    expect(typeFor({ type: "array", items: { anyOf: [{ type: "string" }, { type: "integer" }] } }, "x")).toBe("(string | number)[]");
  });

  it("gives a schema with no type the type unknown, and an open object a record", () => {
    expect(typeFor({ title: "Input" }, "x")).toBe("unknown");
    expect(typeFor({ type: "object" }, "x")).toBe("Record<string, unknown>");
    expect(typeFor({ type: "object", additionalProperties: { type: "boolean" } }, "x")).toBe("Record<string, boolean>");
  });

  it("stops on anything it doesn't handle, naming where and saying what to change", () => {
    const schema: Schema = { allOf: [{ $ref: "#/components/schemas/A" }] };
    expect(() => typeFor(schema, "components.schemas.Mixed")).toThrow(
      "components.schemas.Mixed: this generator doesn't handle the keyword allOf. Extend scripts/openapi-to-ts.ts",
    );
    expect(() => typeFor({ $ref: "https://example.com/schema.json" }, "y")).toThrow("the reference https://example.com/schema.json");
  });
});
