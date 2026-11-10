# A remote MCP server for Odoo Tools: options and threat model

Draft for the product owner, written on 2026-11-10. **Design only.** No remote server,
repository, image, plugin entry or connector exists. Nothing in this document was built,
tested with Claude, submitted or published, and no text may say that it works with Claude
or serves any Odoo.

**Gate G0.** No service that receives real customer credentials is built or published
before a written security-design review by someone who is neither its author nor its
implementer. This document is the input to that review, not the review.

It summarizes three architecture options and six threat models (identity and OAuth, tenants
and secrets, SSRF and egress, permissions and audit, Odoo editions, operations and
compliance), written from the code at commit `182ace3` and from Anthropic's public
documentation as read on 2026-11-10. Effort and cost figures are the author's judgment: no
quote, price or provider was evaluated. Where a statement rests on the documentation only,
it says so.

## 1. Why a remote server is on the table

`docs/product-rules.md` (rule 1) records where new installs come from: 58.7 % claude.ai,
32.6 % Cowork and 8.6 % Claude Code (30 days to 2026-10-27). In claude.ai and Cowork the
local MCP server of the full plugin is not loaded (chat ignores local servers, and Cowork
ignores a server that references a user option with no default, as this plugin's does:
`claude.com/docs/plugins/platform-support`), so 91.3 % of the people who install
Transgenia's plugin get no Odoo tools. A server that Claude reaches over the network is the
only route to them. Rule 4 makes such a server the premium plan: "an MCP server that
Transgenia hosts for a customer is the premium plan, and it is paid".

What Anthropic's documentation says a remote server must meet (read 2026-11-10, not tested
live with Claude):

- A fixed `https://` URL in the plugin loads in chat, Cowork and Claude Code. A URL that
  references a user option (`${user_config.KEY}`) loads only in Claude Code
  (`claude.com/docs/plugins/platform-support`). A connector listing whose users connect to
  different URLs can be published only with the Verified label, so a hosted design uses one
  universal URL.
- In chat and Cowork the call starts in Anthropic's cloud, so the endpoint must be public,
  IPv4 and HTTPS, and reachable from Anthropic's ranges (`160.79.104.0/21` and
  `153.61.208.0/20`, `platform.claude.com/docs/en/api/ip-addresses`). An Odoo behind a firewall or
  only on a LAN cannot be reached that way; those stay on Channel A.
- Authorization is OAuth: a 401 with `resource_metadata`, protected-resource and
  authorization-server metadata, PKCE with S256, client ID metadata documents or dynamic
  registration, the callback `https://claude.ai/api/mcp/auth_callback` for the hosted apps
  and a loopback redirect for Claude Code, and tokens bound to the server (RFC 8707). A
  server must not pass the caller's token on to Odoo.
- Limits: about 150,000 characters per tool result and 240 seconds per tool call on
  claude.ai and Desktop; Claude Code differs (`claude.com/docs/connectors/building`, the
  size and timeout limits; not re-checked after the first read). The latest non-draft MCP
  revision is 2026-07-28 (stateless; dynamic registration deprecated), from the MCP
  specification as first read and not re-checked; Claude's OAuth client is documented up to
  2025-11-25, so a server would speak both until a live test shows which one Claude uses.

## 2. The three options

| | A1: the directory edition now, a hosted server later | A2: a gateway that the customer runs | A3: a multi-tenant server that Transgenia hosts |
|---|---|---|---|
| What | the code-free edition (`distribution/directory`) and Channel A; the hosted server is a later phase | the engine as an HTTPS server next to the customer's Odoo; the plugin adds one remote entry | one universal URL; Transgenia stores each customer's Odoo URL, login and API key |
| Reaches | no Odoo tool on any surface; honest routing and version notes on all three | Claude Code through the plugin; chat and Cowork only through a public OAuth gateway that an administrator adds as a custom connector | chat, Cowork and Claude Code, for public Odoo 14 or later with API keys |
| Transgenia holds credentials | no | no | yes: a custodian of keys and ERP data |
| Effort (author's estimate) | the edition: about 2 to 3 person-weeks | large; XL with chat and Cowork | XL: about 45 to 115 person-weeks from the 17 build items, plus review, penetration test, legal and operations |
| Product rules | fits; rule 3 item 1 needs the owner | rules 4 and 6 need the owner | rule 6 ("diagnostics stay on the user's computer") breaks as written; rules 4 and 5 need the owner |
| Verdict | **GO** for Channel A and the edition once its criteria hold (`docs/directory-channel.md`); **NO-GO** to build the hosted phase before G0 and demand | **conditional**, not the route of the directory edition: it reaches only Claude Code, where Channel A already works; if pursued, an optional gateway plugin in Transgenia's own marketplace after G0 to G3 | **NO-GO to build now**; conditional as the later premium plan behind G0 to G7 |

If the directory refuses a hosted server, a custom connector (a URL a user or an
administrator adds to claude.ai) is the documented fallback. The recommendation is A1 now,
with A3 only as a gated later option and A2 as a possible optional gateway. The edition is
the lowest-risk and lowest-value route: it restores an honest presence in the directory and
a funnel to Transgenia, and gives nobody an Odoo tool.

## 3. What the engine gives and what a server would need

`server/src/odoo_mcp` has 13,891 lines. By the author's count, 59.2 % could be reused as
they are (policy, compat layer, tools, registry, errors, cache, transport base and
signatures), 26.6 % need a refactor (server, session, config, audit, the transports), 2.8 %
a rewrite (tenancy, telemetry, entry point) and 11.4 % do not apply (local diagnostics,
install check). The policy layers are the strongest asset: they run on every call.

A server that holds customers' keys would still need what the engine does not have today:

- an HTTP listener, caller authentication and a per-request context (the engine reads one
  set of credentials from its environment and serves one stdio client);
- real tenancy: `tenancy.py` is a cache keyed by credentials, not isolation, and the
  header-based multi-tenant path was removed in 1.5.0 because the client chose the URL;
- a secret store: keys are plain strings in memory, read from the environment;
- SSRF defences: the transports accept any scheme, host and port the URL names;
- an audit with an actor, tamper-evident and anchored outside the process;
- confirmation before writes: today it is a sentence in the instructions, not a mechanism;
- a policy per caller (the policy schema is per server) and byte and time caps.

## 4. Threat model, by area

Each area lists the threats rated critical or most likely, and the controls that must exist
before a real credential is accepted.

### 4.1 Identity and OAuth

Threats: a spoofed client registers with an attacker's redirect and the victim consents;
login CSRF on the page where the Odoo key is typed binds the key to the attacker's account;
takeover of a person's login; a token minted for another resource is accepted, or the
inbound token reaches Odoo; a connection chosen by anything but the token's subject (a
confused deputy that acts as someone else); an insider with vault access.

Controls: client ID metadata documents first, client IDs allowlisted, exact redirect
matching, consent that names the client's host; PKCE S256; a mature identity provider with
MFA or passkeys and re-authentication before a connection is added or writes are enabled;
the key typed only on a Transgenia page inside the owner's authenticated session, with CSRF
protection, never in the chat, a tool argument or a form elicitation (product rule 5); the
connection resolved only from the verified token subject, with no environment fallback;
audience checks; refresh rotation with reuse detection; revocation and a kill switch per
person. Live conformance on chat, Cowork and Claude Code before any claim.

### 4.2 Tenants and secrets

Threats: `odoo_connections` and the telemetry preview answering for the whole process; a
shared process where object discipline is the only wall ("not malicious code" is the
documented bar of the policy views); plaintext keys living as long as the process; keys in
environment variables, logs, images or backups; one flaw or one KMS grant that reads every
tenant; ciphertext swapped between tenants; a customer-typed URL that reaches the cloud
metadata service and then the key service; staff or break-glass access; an Odoo
administrator key, which no policy of ours narrows once it leaves the vault.

Controls: envelope encryption with a data key per connection and a managed KMS, write-only
(no read back); decrypt authority only through workload identity; no key-bearing call in a
process that serves another tenant; memory hygiene (no core dumps, no object dumps, no
error tracker with locals); fixed error categories and keyed hashes in logs; canary-secret
tests over every sink; an admission test that refuses administrator users or forces
read-only and refuses `http`, user information and passwords; no standing human access to
the production vault, break-glass with two people and a log staff cannot edit; offboarding
and deletion rehearsed.

### 4.3 SSRF, egress and instances Transgenia cannot reach

Threats: a destination in a private, loopback, link-local or reserved range or the metadata
address, including names that resolve there; DNS rebinding between registration and
connect; the key sent to the wrong host after a URL edit; workers that can reach the
metadata service, the vault or the tenant database; a permissive local mode leaking into the
hosted build; an outbound agent or a VPN into a customer's network, which would be a new
and large attack surface.

Controls: a guard that classifies the resolved addresses (not the typed string) and pins the
connection; strict mode as the only mode of the hosted build; a network layer that allows
only a NAT or egress proxy with published static IPs; the secret bound to its origin, so a
URL edit forces a new key entry; byte and ratio caps and one deadline per call below
Claude's 240 seconds; an offline test suite and an external SSRF and rebinding test of the
staging server, with no real credential; the same guard for any fetch of a client-supplied
URL. An Odoo that cannot be reached is said so in plain words (product rule 2); no agent,
VPN or tunnel is built, offered or promised before its own review.

### 4.4 Permissions, audit and confirmation before writes

Threats: the hosted default being `standard`, so an instructed model writes from day one;
`builder`, `full`, `odoo_execute` or automations reachable remotely (automations and server
actions run Python on the customer's Odoo); text in Odoo records (mail, notes, product
descriptions) steering the model; "confirmation before writes" existing only as a sentence;
an audit that is neither attributed to a person nor tamper-evident.

Controls: default `readonly` with withholding; writes opt-in per person with step-up
authorization, a deadline and no refresh past it, decided before any call to Odoo; no
`builder`, `full`, schema tools or `odoo_execute` in v1, absent from the tool list and not
only disabled; titles and annotations on every tool and a `destructiveHint` on every write;
row, id and byte caps; a per-tenant audit chain with opaque keys, a write-ahead intent
record, a KMS-keyed or signed chain and external checkpoints; an injection drill in a
synthetic tenant, reported as measured and never as immunity.

### 4.5 Odoo editions and versions

Threats: storing the account password for Odoo 10 to 13, which has no API keys (it is also a
web login, with no scope or expiry); API keys that expire from Odoo 18, and on Odoo Online
need the Custom plan; the legacy endpoints that Odoo plans to remove (Odoo 22, Odoo Online
saas~21.1), after which only JSON-2 and API keys remain; a test rig (plain `http` on
loopback, admin account) that weakens the production guard if it is reused.

Controls: API keys only, so Odoo 14 or later and public instances; a compatibility promise
per version that Transgenia has tested, nothing wider; the strict guard in CI as in
production; key-expiry tracking and a clear message when a key expires.

### 4.6 Operations, cost, availability and compliance

Threats: an outage that leaves chat and Cowork users without a local fallback (only Claude
Code can fall back to Channel A); a liveness check that Transgenia cannot see (an allowlist
at the network layer that drops unknown sources is worse than a 401 at the application
layer); texts that become false, such as "Transgenia operates no server for it"
(`PRIVACY.md`) and the credential statements of `SECURITY.md` and the Terms of Use, which
describe the local edition; no processor terms for customers' ERP data.

Controls: two zones, stateless workers, a status page hosted apart, runbooks and no SLA
until paying demand exists; own probes from two vantage points; a privacy policy URL, a
data processing agreement, terms, a list of subprocessors, a breach procedure and a
retention table, drafted with counsel; hosted legal texts that leave the local edition's
texts unchanged; the manual in Spanish, English and Chinese (rule 8).

## 5. Gates

All must hold before a real credential is accepted, and none holds today.

| Gate | Condition |
|---|---|
| G0 | The written independent security-design review of this design, the vault, the key page and the egress design; findings closed or accepted in writing by the product owner. No real credential in any demo or reviewer account. |
| G1 | The product owner decides in writing that Transgenia becomes a processor of Odoo credentials and ERP data (rules 4, 5 and 6), the price and entitlement, and whether the hosted code is private; `PRIVACY.md`, `SECURITY.md` and the Terms are scoped to the local edition. |
| G2 | Anthropic answers in writing: the policy on customer-owned hosts, the extra review of a remote server from a publisher that is not Verified, and a listing that is paid. A stub connector with no credentials and no Odoo is tested as a custom connector on claude.ai, Cowork and Claude Code, which settles the MCP revision, dynamic registration versus client ID metadata, and the limits. |
| G3 | Demand: named customers with a reachable Odoo 14 or later who agree to pay; otherwise the fixed cost has no owner. |
| G4 | The engine prerequisites are merged in the MIT repository first (they hold no credential and also help Channel A): SSRF strict mode that passes an offline checklist, body caps, a total deadline, a per-request context with unchanged stdio output. |
| G5 | The hosted suites pass: two-tenant isolation, canary secrets in logs, audit and errors, policy fuzz under the hosted default, the official MCP client over HTTP and OAuth, SSRF against a metadata-service stub; an independent penetration test before general availability. |
| G6 | Safe defaults ship: read-only profile, writes opt-in, no `odoo_execute` or automation tools, administrator keys refused or read-only, tenant kill switch tested. |
| G7 | Legal and documentation are ready: privacy policy, processing agreement, terms, subprocessors, breach procedure, retention; the manual in three languages; Odoo S.A.'s terms for third-party API clients checked (not checked here); on-call named. |

## 6. Decisions for the product owner

1. Whether to commission the G0 review, and by whom. Nothing else in this document starts
   before it.
2. Whether Transgenia may become a processor of customers' Odoo credentials and data
   (rules 4, 5 and 6), and at what price.
3. Whether to send Anthropic the questions of G2 now. They cost nothing and decide whether
   the hosted route can be listed at all (`docs/directory-channel.md`, section 8).
4. Whether the optional customer-run gateway (A2) is worth a pilot after G0 to G3.
5. The isolation level (a process per tenant or shared workers), the identity provider and
   the cloud provider. No option was priced.

## 7. What was not verified

- How Claude behaves with such a server: nothing was tested live (revision, dynamic
  registration or client ID metadata, annotations, step-up, elicitation).
- Anthropic's review of a remote server from a publisher that is not Verified.
- Odoo S.A.'s terms for third-party API clients, and the legal texts a hosted service needs
  (counsel is required).
- Effort, price and availability figures: the author's judgment, not a quote.
- The Odoo-side claims (key expiry, the Custom plan, planned endpoint removals) are the
  repository's own statements (`docs/compat-matrix.md`, `server/src/odoo_mcp/tools/online.py`),
  not re-verified against Odoo.
