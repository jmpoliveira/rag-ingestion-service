# Tessera Support Cloud: Administrator Guide

This guide is for workspace owners and administrators. It covers the settings that shape how
your team works in Tessera: who can do what, how customers reach you, how tickets are
organised and automated, how quality is measured, and how the workspace is secured. For
prices and plan limits, see the Plans and pricing article; for our own support response
times, see the SLA article.

## 1. Workspace basics

Every workspace has a name, a subdomain and a default time zone. The subdomain becomes part
of your public addresses, for example `acme.tessera.help` for the help centre and the email
forwarding address described in section 4. You can change the workspace name at any time.
Changing the subdomain breaks existing links to your help centre, so Tessera keeps a redirect
from the old subdomain for 90 days.

The default time zone is used for reports, for business-hours calendars and for the dates
shown to agents. Each agent can override it in their own profile, which only changes how
dates are displayed to them.

### Business-hours calendars

A business-hours calendar defines when your team is working: opening hours per weekday and a
list of holidays. Calendars are used by your own SLA policies (section 9) and by automations
that should only act during working hours. Pro workspaces have one calendar; Enterprise
workspaces can define up to 20, for example one per region.

## 2. Roles and permissions

Tessera has four roles. Each person in the workspace has exactly one.

- **Owner.** There is one owner per workspace. The owner manages billing, can delete the
  workspace and is the only person who keeps a password login when single sign-on is
  enforced. Ownership can be transferred to an administrator from the billing page; the
  previous owner becomes an administrator.
- **Administrator.** Administrators change every workspace setting except billing and
  deletion: channels, fields, automations, security settings, integrations and roles.
- **Agent.** Agents work on tickets: they reply to customers, change status and priority,
  apply macros and create views for themselves.
- **Light agent.** Light agents can view tickets and add internal notes, but cannot reply to
  customers and cannot change a ticket's status or priority. They are meant for colleagues
  outside the support team, such as engineers or account managers, who need to follow or
  comment on a case. Light agents are free of charge and unlimited on Pro and Enterprise; Free
  workspaces do not have this role.

Only owners and administrators can change roles. A change takes effect at the agent's next
request, and it is recorded in the audit log on Enterprise.

### Groups

Groups collect agents who handle the same kind of work, for example "Billing" or "Level 2".
Tickets can be assigned to a group and then picked up by one of its members. An agent can
belong to several groups. Groups are available on Pro and Enterprise.

## 3. Inviting and removing agents

Administrators invite agents by email from the team page. The invitation link expires after
7 days; an expired invitation can be sent again. An invited person counts as a seat only once
they accept.

Removing an agent frees their seat immediately. Their tickets stay assigned to them until you
reassign them; the team page lists tickets that are still assigned to removed agents, so they
are not forgotten. Removed agents lose access at once, including any open session.

## 4. Channels

Channels are the ways customers reach you. Every channel creates tickets in the same queue.

- **Email.** Each workspace receives an address of the form `support@<subdomain>.tessera.help`.
  Forward your own support address to it, and Tessera turns every email into a ticket or a
  reply on an existing ticket. Replies from agents are sent from your own address once you
  verify your domain with the DNS records shown in the channel settings.
- **Chat.** A chat widget for your website, available on Pro and Enterprise. Conversations
  that are not answered within the configured time become tickets automatically.
- **Web forms.** Forms on your help centre, with the fields you choose. Available on Pro and
  Enterprise.

Free workspaces have the email channel only.

## 5. Ticket fields and custom fields

Every ticket has standard fields: requester, subject, status, priority, assignee, group and
tags. Custom fields add information specific to your business, such as an order number, a
product or a contract type.

A Pro workspace can define up to 50 custom fields; an Enterprise workspace up to 200. The
available field types are text, number, date, checkbox, drop-down list and multi-select. A
custom field can be required before a ticket is resolved, which is a common way to make sure
agents record a cause or a product for every case.

Deleting a custom field removes it from every ticket, including closed ones, and cannot be
undone. To stop using a field without losing its history, deactivate it instead.

## 6. Views and queues

Views are saved lists of tickets that match conditions, such as "open tickets in the Billing
group, oldest first". Administrators create shared views for the whole team; agents can create
personal views. A workspace can have up to 100 shared views.

The default "Unassigned" view shows every open ticket without an assignee. Most teams use it
as their main queue.

## 7. Macros

A macro is a saved set of actions that an agent applies in one click: a reply text, a status
change, tags, a priority or an assignment. Macros keep answers consistent and save time on
frequent questions. A workspace can store up to 500 macros. Macros can be shared with the
whole team, with a group, or kept personal.

Macros can include placeholders, such as the requester's first name or the ticket number,
which are filled in when the macro is applied.

## 8. Triggers and automations

Tessera has two kinds of rules that act on tickets without an agent.

**Triggers** react to events. They run immediately when a ticket is created or updated and
its conditions match, for example "when a ticket arrives from a VIP customer, set the priority
to high and notify the Level 2 group".

**Automations** are time-based. They check every ticket every 15 minutes and act on those
whose conditions have been true for long enough, for example "when a ticket has been pending
for 3 days, send a reminder to the customer". The built-in automation that closes resolved
tickets after 7 days without a reply (see the Ticket lifecycle article) is an automation of
this kind; it can be disabled but not changed.

Because automations run on a 15-minute cycle, a condition such as "pending for 2 hours" is
acted on between 2 hours and 2 hours and 15 minutes after it became true.

## 9. SLA policies for your own customers

The SLA article describes how quickly the Tessera support team answers you. SLA policies are
different: they are the targets *you* promise to *your* customers, and Tessera measures your
team against them.

An SLA policy sets first-reply and resolution targets per priority, and uses one of your
business-hours calendars. The clock pauses while a ticket is pending on the customer. Tickets
close to breaching a target are highlighted in views, and triggers can react to "SLA breached"
events. SLA policies are available on Pro and Enterprise.

## 10. Customer satisfaction surveys

When satisfaction surveys are enabled, the customer receives a short survey 24 hours after a
ticket is resolved, asking whether they were satisfied with the help they received, with an
optional comment. Only one survey is sent per ticket, even if it is reopened and resolved
again. If the customer reopens the ticket before the 24 hours have passed, the survey is not
sent.

Results appear on the ticket and in the satisfaction report, per agent, group and channel.

## 11. Reports and exports

The reporting page shows ticket volume, first-reply time, resolution time and satisfaction,
filtered by date range, channel, group or agent.

Tickets can be exported as a CSV file. One export can contain up to 100,000 tickets; larger
data sets are split by date range. Scheduled exports, delivered daily or weekly to an email
address or a storage bucket, are available on Enterprise.

## 12. Security settings

- **Two-factor authentication.** Any agent can turn it on. On Pro and Enterprise,
  administrators can make it mandatory for everyone in the workspace.
- **Session length.** Agent sessions end after 12 hours of inactivity by default.
  Administrators can choose between 1 and 72 hours.
- **IP allowlist.** Enterprise workspaces can restrict agent access to a list of IP address
  ranges, such as an office network or a VPN. Up to 50 ranges can be listed. Agents outside
  the allowed ranges cannot sign in. The owner is always allowed, to avoid locking everyone out.
- **Audit log.** Enterprise workspaces keep an audit log of administrative changes: role
  changes, setting changes, exports and sign-ins. Entries are kept for 1 year and can be
  exported.
- **Single sign-on.** See the Account security article.

## 13. Integrations and API tokens

Tessera integrates with Slack, Microsoft Teams and Jira from the integrations page; each
integration has its own article. Integrations act with the permissions of the administrator
who installed them.

For custom integrations, administrators create API tokens. A token belongs to the
administrator who created it and inherits their permissions. Tokens are shown once, at
creation; store them in a secrets manager. Revoking a token takes effect immediately. See the
REST API overview for authentication and limits.

## 14. Importing data

Tickets and customers can be imported from CSV files from the data page. Imported tickets keep
their original creation dates and are marked as imported. Enterprise customers moving from
another helpdesk can ask for an assisted migration, planned with their customer success
manager.

## 15. Deleting the workspace

Only the owner can delete the workspace, from the billing page. Deletion follows the same rule
as cancellation: the data is kept for 60 days so the workspace can be restored, then deleted
permanently. During those 60 days nobody can sign in.
