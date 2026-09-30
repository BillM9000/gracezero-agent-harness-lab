# Runbook: <the service>

<!-- Ship. What someone on call needs, at the service's stage. A section marked [from STAGE] may
stay unfilled until the service reaches that stage, and must be filled once it has: moving a service
to a later stage means filling in its sections first. Check it with:
node tools/kit.mjs doc templates/ship/runbook.md YOUR-RUNBOOK.md -->

**Stages:** Alpha, Beta, Production, Maintenance
**Stage:** <Alpha, Beta, Production or Maintenance>
**Owner:** <who answers for it, and how to reach them>

## What it is and who depends on it

<One paragraph: what it does, who uses it, and what stops working when it's down.>

## How to run it

<The commands that set it up and run it on a fresh machine, and what a healthy start prints.>

## How to deploy [from Beta]

<The exact steps, the gates they pass, and how to tell a deploy worked.>

## How to roll back [from Beta]

<The exact steps, how long they take, and what is lost.>

## Known issues [from Beta]

- <What's wrong, its workaround, and the day it was last seen.>

## Monitoring and alerts [from Production]

<What is watched, what each alert means, and where it goes.>

## Incident response [from Production]

<The first five minutes: who to tell, what to check, and how to stop the damage.>

## Backups and recovery [from Production]

<What is backed up, how often, and the steps to restore it, tried at least once.>

## Retirement [from Maintenance]

<What would make it time to retire the service, and who decides.>
