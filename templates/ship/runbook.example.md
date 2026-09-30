# Runbook: the lab's helpdesk

<!-- A filled example of templates/ship/runbook.md, for the lab's helpdesk as if it were a service
at the Beta stage. The sections marked [from Production] and [from Maintenance] wait for those
stages, so they're still placeholders. -->

**Stages:** Alpha, Beta, Production, Maintenance
**Stage:** Beta
**Owner:** Sam Rivera, through the support team's channel

## What it is and who depends on it

The helpdesk's API (FastAPI on SQLite): tickets, replies and the knowledge base, for support staff and the triage assistant. When it's down, staff can't read or answer tickets, and the assistant's tools fail.

## How to run it

From the repository's root, `node setup.mjs`, then from `python/`, `uvicorn --factory helpdesk.main:create_default_app`. A healthy start prints "Application startup complete", and `GET /health` answers `{"ok": true}`.

## How to deploy [from Beta]

Run `node check.mjs` on the commit to deploy, fill in a release card and have a lead sign it, then start that commit where the service runs. A deploy worked when `GET /health` answers and `GET /tickets` lists the open tickets.

## How to roll back [from Beta]

Start the previous release's commit. It takes a minute; the database isn't changed by a deploy, so nothing is lost.

## Known issues [from Beta]

- None open as of 2026-09-30.

## Monitoring and alerts [from Production]

<What is watched, what each alert means, and where it goes.>

## Incident response [from Production]

<The first five minutes: who to tell, what to check, and how to stop the damage.>

## Backups and recovery [from Production]

<What is backed up, how often, and the steps to restore it, tried at least once.>

## Retirement [from Maintenance]

<What would make it time to retire the service, and who decides.>
