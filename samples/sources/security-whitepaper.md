# Tessera Security Whitepaper

## How we protect your support data

Version 3, October 2026.

Support tickets hold some of the most sensitive information a company has: customer names,
contracts, invoices, and the details of what went wrong. This whitepaper describes how Tessera
Support Cloud protects that information: the certifications we hold, how data is encrypted,
how our infrastructure and our people are controlled, how we build and test the product, and
what happens when something goes wrong.

It is written for security and compliance teams evaluating Tessera, and complements the Data
retention and privacy and Account security articles of the help centre.

Each section stands on its own page, so that it can be shared or quoted separately in a vendor
assessment.

<!-- page -->

## 1. Compliance and certifications

Tessera's information security management system is certified to ISO/IEC 27001. The
certification covers the Service, its infrastructure and the teams that build and operate it,
and is renewed every three years with yearly surveillance audits by an accredited
certification body.

An independent auditor also assesses our controls against the SOC 2 Trust Services Criteria
for security, availability and confidentiality. The SOC 2 Type II report is available to
customers and prospects on request, under a non-disclosure agreement.

As a processor of personal data under the GDPR, Tessera signs a Data Processing Agreement with
every customer. The agreement includes the standard contractual clauses for any transfer of
personal data outside the European Economic Area, and lists our sub-processors, which are also
published on the trust page.

<!-- page -->

## 2. Encryption

All customer data is encrypted at rest with AES-256, including databases, file storage for
attachments, search indexes and backups.

All data in transit is encrypted with TLS 1.2 or higher, both between customers and the
Service and between our own internal services. Older protocol versions and weak cipher suites
are disabled, and HTTP Strict Transport Security is enforced on every public address.

Encryption keys are managed in a cloud key management service and are never stored next to
the data they protect. Keys are rotated every year, and access to the key service is limited
to the automated systems that need it.

Enterprise customers can bring their own key: data is then encrypted with a key held in the
customer's own key vault, and revoking that key makes the workspace's data unreadable.

<!-- page -->

## 3. Infrastructure and network

The Service runs on a major cloud provider in the European Union, in the Frankfurt and Dublin
regions, each spread over several availability zones.

Production networks are segregated from corporate and development networks. Only the public
web endpoints are reachable from the internet, behind a web application firewall and
distributed denial-of-service protection. Databases and internal services accept connections
only from the services that need them.

Infrastructure is defined as code and reviewed like application code. Servers are not changed
by hand: every change is a reviewed commit, deployed by the pipeline, which keeps
environments reproducible and every change traceable.

Operating systems and container images are patched automatically; critical security patches
are applied within 72 hours of their release.

<!-- page -->

## 4. Access control

Tessera staff follow the principle of least privilege. Nobody has standing access to
production systems or to customer data.

When an engineer needs production access, for example to investigate an incident, the access
is requested, approved by a second person, granted for at most 4 hours and then removed
automatically. Every session is logged, and the logs are kept for one year in a separate
account that engineers cannot modify.

Support staff can see a customer's workspace only when the customer grants access from a
ticket, and that access ends when the ticket is closed.

All staff sign in with single sign-on and phishing-resistant multi-factor authentication. New
employees are background-checked where local law allows, complete security training before
getting any access, and repeat it every year.

<!-- page -->

## 5. Application security

Security is part of how we build the product. Every change is reviewed by a second engineer
before it is merged, and the pipeline runs static analysis, dependency vulnerability scanning
and secret detection on every commit.

The Service is tested by an independent third party through a penetration test at least once a
year, and after any major architectural change. A summary of the latest results is available
to customers under a non-disclosure agreement.

We also run a public bug bounty programme. Security researchers can report vulnerabilities
through the trust page; we acknowledge reports within two business days and do not take legal
action against good-faith research that follows the programme rules.

<!-- page -->

## 6. Incident response

A security team is on call 24 hours a day, 7 days a week, with documented procedures for
detecting, containing and recovering from incidents. The procedures are rehearsed twice a year.

If we confirm a security breach that affects a customer's personal data, we notify the
affected customers within 72 hours of confirming it, by email to the workspace owner and in
the workspace. The notification describes what happened, the data concerned and the measures
taken, as far as they are known at that time.

A written post-incident report, with the root cause and the actions taken to prevent a
recurrence, follows within 10 business days.

<!-- page -->

## 7. Business continuity and backups

Customer data is backed up every 6 hours to a separate region, and backups are kept for 35
days before being overwritten, as described in the Data retention and privacy article.

Our recovery objectives are a recovery point objective (RPO) of 6 hours, the most data that
could be lost, and a recovery time objective (RTO) of 4 hours, the time to restore the Service
in another region after the loss of a whole region.

Restoring from backups is tested every month on a sample of data, and the full disaster
recovery plan, including a regional failover, is tested twice a year.

<!-- page -->

## 8. Data deletion and contact

When a customer deletes data, it is removed from the live systems at once and disappears from
backups as they expire. When a workspace is cancelled, its data is kept for 60 days so it can
be restored, then permanently deleted. The Data retention and privacy article has the details.

Questions about this whitepaper, requests for the SOC 2 report or the penetration test
summary, and security reports can be sent through the trust page or to
security@tessera.example.
