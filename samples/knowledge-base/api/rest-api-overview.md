# REST API overview

The Tessera REST API lets you read and change tickets, customers and users from your own
systems. It is available on Pro and Enterprise.

## Authentication

Every request carries an API token in the `Authorization` header as a bearer token. Tokens are
created by administrators (see the Administrator Guide) and inherit their permissions. Requests
without a valid token receive `401 Unauthorized`.

The base URL is `https://<subdomain>.tessera.help/api/v2`. All requests and responses use JSON
and UTF-8.

## Rate limits

Pro workspaces can make up to 600 requests per minute; Enterprise workspaces up to 2,400.
The limit applies to the whole workspace, not to each token. When it is exceeded, the API
answers `429 Too Many Requests` with a `Retry-After` header in seconds; wait that long before
retrying.

## Tickets

| Method and path | Purpose |
|---|---|
| `GET /tickets` | List tickets, newest first, filtered by `status`, `priority`, `group` or `requester` |
| `GET /tickets/{id}` | One ticket with its fields |
| `POST /tickets` | Create a ticket |
| `PATCH /tickets/{id}` | Change status, priority, assignee, tags or custom fields |
| `GET /tickets/{id}/comments` | Replies and internal notes, oldest first |

Ticket statuses in the API are `open`, `in_progress`, `resolved` and `closed`, as in the
Ticket lifecycle article. Priorities are `low`, `medium` and `high`.

## Pagination

List endpoints return up to 100 items per page and a `next_cursor` value. Pass it as the
`cursor` parameter to get the next page. A missing `next_cursor` means the last page.

## Webhooks

Webhooks send a POST request to your endpoint when tickets are created or updated. If your
endpoint does not answer with a 2xx status within 10 seconds, Tessera retries up to 5 times
over 24 hours, with increasing intervals. After the last failure the delivery is dropped and
listed in the webhook log for 30 days.

Each delivery is signed with an HMAC-SHA256 signature in the `X-Tessera-Signature` header,
computed with the webhook's secret. Verify it before trusting the payload.

## Errors

Errors use standard HTTP status codes and a JSON body with a `code` and a human-readable
`message`. Validation errors (`422`) list the fields that failed.
