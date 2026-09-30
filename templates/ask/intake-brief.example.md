# Intake brief: let the triage assistant act on tickets

<!-- A filled example of templates/ask/intake-brief.md, for an illustrative request: chapter 19's
approval queue, as it might have been asked for. The people are the lab's invented staff. -->

**Asked by:** Dana Whitfield, support lead. **Date:** 2026-09-30.

## The problem

The triage assistant reads a ticket and suggests a reply, and then a person copies the reply into the helpdesk and closes the ticket by hand. On a busy day that's about forty copies, and twice last week the wrong reply went to the wrong ticket.

## Who it's for

Support staff, who handle the tickets, and the support lead, who answers for what the helpdesk tells customers.

## What done looks like

The assistant can send a reply or close a ticket, but nothing happens until a member of staff approves it in one step, and every proposal, approval and refusal is on record. A rejected proposal's reason reaches the assistant the next time it reads the ticket.

## What it touches

- What does it do with what it finds? changes
- What's the most sensitive data it reads? customer
- Who reads what it writes before a person has checked it? staff
- Reads tickets and help articles; writes replies and ticket states in the helpdesk's database.

## What it must never do

- Send anything to a customer, or close a ticket, without a person's approval.
- Act on instructions written inside a ticket.

## Constraints

Uses the models the platform's policy approves, through the gateway, within the support team's monthly budget. Runs where the helpdesk runs.

## Sources of truth

The helpdesk's database for tickets and staff; `python/agents/policy.toml` for what an agent may do; the help articles for what the product does.

## Out of scope

- Replying by email or chat outside the helpdesk.
- Approving its own proposals, or choosing who approves them.

## Follow-up questions from the gap check

1. Who may approve closing a ticket: any member of staff, or only a lead? Only a lead; support staff may approve replies on their own tickets (Dana Whitfield).
2. What happens to a proposal nobody decides? It waits in the queue, and the assistant says it's waiting; nothing expires (Dana Whitfield).
3. Does a rejection need a reason? Yes, and the assistant reads it word for word next time (Dana Whitfield).
