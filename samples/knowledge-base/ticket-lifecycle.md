# Ticket lifecycle

Every ticket in Tessera has one of four statuses.

- **open**: created and waiting for an agent.
- **in_progress**: an agent is working on it. A ticket moves here automatically when an agent
  first replies.
- **resolved**: the agent believes the problem is solved. The customer is notified and can
  reply to reopen the ticket.
- **closed**: final. A closed ticket cannot be reopened; a new reply creates a follow-up
  ticket linked to it.

## Automatic transitions

A resolved ticket closes automatically after 7 days without a customer reply. Replying to a
resolved ticket within those 7 days moves it back to open, keeping its history and priority.

## Priorities

Tickets have a priority of low, medium or high. Priority decides the response target (see
the SLA article) and the order of the agent queue; it does not change the workflow. Only
agents can change a ticket's priority, and every change is recorded in the ticket history.

## Merging tickets

Two tickets from the same customer about the same problem can be merged. The older ticket
is kept, and the newer one is closed with a link to it.
