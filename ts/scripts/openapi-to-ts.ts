// Turns the schemas in an OpenAPI document into TypeScript types (chapter 7): one exported type
// per schema, so the client's types come from the same contract as the service's.
//
// It covers what the helpdesk's contract uses: objects, strings, numbers, booleans, null, enums,
// arrays, references and unions. Anything else stops it with an error naming where it was found,
// rather than a guess. For a real API, reach for an established generator; this one is small
// enough to read.

export interface Schema {
  type?: string | string[];
  properties?: Record<string, Schema>;
  required?: string[];
  items?: Schema;
  enum?: unknown[];
  anyOf?: Schema[];
  oneOf?: Schema[];
  $ref?: string;
  additionalProperties?: boolean | Schema;
  description?: string;
  [keyword: string]: unknown;
}

export interface OpenApiDocument {
  components?: { schemas?: Record<string, Schema> };
  [key: string]: unknown;
}

// Keywords that shape the type, and keywords that only describe or validate values.
const SHAPING = ["type", "properties", "required", "items", "enum", "anyOf", "oneOf", "$ref", "additionalProperties"];
const DESCRIBING = ["title", "description", "default", "examples", "format", "minLength", "maxLength", "pattern"];
const DESCRIBING_NUMBERS = ["minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"];
const KNOWN = new Set([...SHAPING, ...DESCRIBING, ...DESCRIBING_NUMBERS]);

export const HEADER = [
  "// Generated from contracts/openapi.json by scripts/api-types.ts. Don't edit it by hand: change the",
  "// Python models, regenerate the contract, then run npm run api-types.",
].join("\n");

function unsupported(where: string, what: string): never {
  throw new Error(`${where}: this generator doesn't handle ${what}. Extend scripts/openapi-to-ts.ts rather than editing src/api-types.ts by hand.`);
}

const identifier = (name: string) => (/^[A-Za-z_$][\w$]*$/.test(name) ? name : JSON.stringify(name));

function refName(ref: string, where: string): string {
  const match = /^#\/components\/schemas\/([A-Za-z_$][\w$]*)$/.exec(ref);
  if (!match?.[1]) unsupported(where, `the reference ${ref}`);
  return match[1];
}

function fields(schema: Schema, where: string, indent: string): string[] {
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {}).map(
    ([name, property]) => `${indent}${identifier(name)}${required.has(name) ? "" : "?"}: ${typeFor(property, `${where}.${name}`)};`,
  );
}

// The TypeScript type for one schema. `where` names the place for error messages.
export function typeFor(schema: Schema, where: string): string {
  const extra = Object.keys(schema).filter((key) => !KNOWN.has(key));
  if (extra.length > 0) unsupported(where, `the keyword ${extra.join(", ")}`);
  if (schema.$ref !== undefined) return refName(schema.$ref, where);
  if (schema.enum !== undefined) return schema.enum.map((value) => JSON.stringify(value)).join(" | ");
  const union = schema.anyOf ?? schema.oneOf;
  if (union !== undefined) return union.map((member, i) => typeFor(member, `${where}[${i}]`)).join(" | ");
  if (Array.isArray(schema.type)) return schema.type.map((type) => typeFor({ ...schema, type }, where)).join(" | ");
  switch (schema.type) {
    case undefined:
      if (schema.properties === undefined) return "unknown"; // a schema with no type allows any value
      return `{ ${fields(schema, where, "").join(" ")} }`;
    case "string":
      return "string";
    case "integer":
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "null":
      return "null";
    case "array": {
      if (schema.items === undefined) unsupported(where, "an array without items");
      const item = typeFor(schema.items, `${where}.items`);
      return item.includes(" | ") ? `(${item})[]` : `${item}[]`;
    }
    case "object": {
      if (schema.properties !== undefined) return `{ ${fields(schema, where, "").join(" ")} }`;
      const values = schema.additionalProperties;
      return `Record<string, ${typeof values === "object" ? typeFor(values, `${where}.additionalProperties`) : "unknown"}>`;
    }
    default:
      return unsupported(where, `the type "${schema.type}"`);
  }
}

// The whole generated file: the header, then one declaration per schema, in the contract's order.
export function generate(doc: OpenApiDocument): string {
  const schemas = doc.components?.schemas ?? {};
  const blocks = Object.entries(schemas).map(([name, schema]) => {
    const where = `components.schemas.${name}`;
    const comment = schema.description ? `/** ${schema.description} */\n` : "";
    if (schema.type === "object" && schema.properties !== undefined) {
      typeFor(schema, where); // reject anything unsupported before writing the interface
      return `${comment}export interface ${name} {\n${fields(schema, where, "  ").join("\n")}\n}`;
    }
    return `${comment}export type ${name} = ${typeFor(schema, where)};`;
  });
  return `${HEADER}\n\n${blocks.join("\n\n")}\n`;
}
