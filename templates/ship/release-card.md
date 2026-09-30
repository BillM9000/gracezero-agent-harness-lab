# Release card: <the service> <the version>

<!-- Ship. One page a person reads and signs before a release goes out: what ships, the evidence
that each gate passed, and the declaration of exactly what is deployed where. A deploy that ships
any other commit, or to any other environment, isn't this release. Check it with:
node tools/kit.mjs doc templates/ship/release-card.md YOUR-CARD.md -->

## What ships

- <Each change, with its feature id or change record.>

## Gates, with evidence

| Gate | Evidence | Result |
|---|---|---|
| <A check or approval the release needs> | <the command, run, or record that shows it> | <passed, on YYYY-MM-DD> |

## Risks and rollback

<What could go wrong, what the first sign would be, and the steps that undo the release.>

## Deploy declaration

- **Commit:** <the full commit id that ships>
- **Environment:** <where it goes, such as production>
- **Signed by:** <name, role>
- **Signed at:** <YYYY-MM-DD HH:MM, and the time zone>
