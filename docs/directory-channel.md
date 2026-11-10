# Distribution channels and Anthropic's directory

Draft for the product owner, written on 2026-11-10 after the directory refused
v1.6.1. No submission to Anthropic has been made for anything described here.
Where a fact comes from Anthropic's public documentation it says
**official** and names the page; where it comes only from the review portal's text
for v1.6.1 it says **portal only**; the rest is Transgenia's own reading.

## 1. What happened

On 2026-11-08 Anthropic's automatic check refused v1.6.1 (commit `182ace3`):
"Directory policy refused this version", decided by an automatic check. The live
version is still v1.4.0 (commit `26de374`, live since 2026-10-05). The security scan
passed (portal only); a passing scan is not a permission to publish, because the policy check is a
separate decision. v1.4.1 and v1.5.0 had been held earlier for "Uses a credential from
the user's machine" (`docs/packaging.md`), a hold and not a refusal.

The portal named three blocking findings and eight others (section 4). The three
blocking ones come from one rule that applies to a publisher that is not a Verified
organization: no command hook, no MCP server that runs on the user's computer, and no
file outside Markdown, text, JSON, YAML and a few image types. v1.4.0 already had a
command hook, the server and the code files; v1.4.1 and v1.5.0, which were updates
with a hook, were held for the credential finding, and `docs/packaging.md` records no
mention of the hook, the server or the file types in those reviews. So the rule seems
to be newer than the review of v1.5.0 (2026-10-23), but the portal does not say since
when it applies (question 1 in section 8).

## 2. Decision

The full plugin cannot satisfy that rule and stay what it is: its value is a local MCP
server, hooks and scripts. Removing them to please a scanner would end the product.
Transgenia therefore keeps two channels, each with its own folder and its own checks:

| | Channel A: the full local plugin | Channel B: the directory edition |
|---|---|---|
| Folder | the repository root | `distribution/directory/` |
| Contents | MCP server, hooks, scripts, CLI, skills, commands, agents | skills and one command, Markdown, JSON and one PNG: no code |
| Reaches users through | Transgenia's own marketplace and the release zip (the desktop extension is a CI preview for manual testing, not published) | Anthropic's directory, once submitted with that folder as the plugin path |
| Review by Anthropic | none (official: a marketplace you add yourself has no submission form and no review) | yes, as a new submission |
| Can read or change Odoo | yes, in Claude Code | no, by design |
| Checked by | CI (ruff, pytest, product rules) | `scripts/directory_preflight.py` in CI, and the tests of `distribution/directory` |

Channel B alone gives the directory's audience a reference skill and a way to reach
Transgenia. It does not connect Claude to Odoo. Tools for the 91 percent of installs
that come from claude.ai and Cowork (`docs/product-rules.md`, rule 1) need a remote
MCP server, which does not exist: see `docs/design/remote-mcp-threat-model.md`.

## 3. Facts that decide the architecture

1. **official** (`claude.com/docs/plugins/submit.md`): the submission takes a
   repository, an optional plugin path (the folder that holds
   `.claude-plugin/plugin.json`) and an optional tracked branch or tag. "If the plugin
   is one folder in a larger repository, give that folder as the plugin path when you
   submit; the directory reads and scans only that folder." Most checks read that
   folder, and a few also read the rest of the repository
   (`claude.com/docs/plugins/pre-submission-checklist.md`).
2. **official** (`submit.md`): a submission's repository and folder cannot be changed
   after it is made. To list a plugin from another folder, create a new submission.
   So the edition is a new listing and the live `odoo-tools` listing stays as it is.
3. **official** (`submit.md`): a version that does not pass, or is held for a reviewer,
   does not take the listing down: the last published version keeps being served.
   (`pre-submission-checklist.md`): "A hold isn't a rejection."
4. **official** (Anthropic Software Directory Terms and Policy): Anthropic may remove a
   listing for a change of its Policy, and material changes may be re-reviewed.
   (`directory/publish.md`): a plugin bundle is "checked again with each new version".
   No grandfathering is promised. The announcement of 2026-09-25 said existing listings
   need no changes at that rollout (`claude.com/blog/build-plugins-for-claude`), which
   does not bind a later policy. So v1.4.0 can be re-reviewed or removed at any time.
5. **official**: "Verified" is documented as a label on directory listings. For
   connectors it means Anthropic tested the tools, and there is "no separate
   application" for it (`claude.com/docs/connectors/verification.md`,
   `directory/publish.md`). Plugin cards also show "Verified" or "Community" (support
   article 17740565, `anthropic-marketplaces.md`), with no criteria. The concept of a
   Verified organization, and the three rules above, are **portal only**: no public
   Anthropic page states them. The public checklist is narrower: it holds for a reviewer
   a hook or a local MCP server command that runs a non-shell file the validator cannot
   read through, and any binary file; and it Blocks an inline program such as `python3 -c`
   in a hook or server command (the second hook of `hooks/hooks.json` is one, and the
   portal did not name it). The portal itself says there is no way to ask to become
   Verified yet.
6. **official** (`anthropic.com/news/services-track-partner-hub`): Registered is the
   entry level of the partner program and partnership begins at Select. No Anthropic
   text links partner tiers to Verified or to the directory. Transgenia's own record is
   the Registered tier (the product owner's statement: no Anthropic page read for this
   document states it). Being at the Registered tier is not being Verified, and
   Transgenia must not be described as Verified.
7. **official** (`code.claude.com/docs/en/plugins/publish.md`,
   `claude.com/docs/plugins/overview.md`): a plugin published in a repository's own
   marketplace needs no submission form, Anthropic does not review it, and claude.ai
   and Cowork users can add a GitHub marketplace themselves. This is Channel A's route.
8. **official**: a plugin may carry a remote MCP server (type `http`, an absolute
   `https://` URL or a `${user_config.KEY}` reference). By app
   (`claude.com/docs/plugins/platform-support`): a fixed URL is listed in chat and
   loads in Cowork and in Claude Code; a URL that references a user option is ignored
   in chat, is ignored in Cowork when the option has no default, and loads in Claude
   Code. A connector listing whose users connect to different URLs can be published
   only once it has the Verified label (`claude.com/docs/connectors`).

## 4. Findings of the portal for v1.6.1

"Class" is Transgenia's reading after reading the code. A blocking finding stops the
version; a warning may be confirmed by a reviewer; a note needs no action.

| Code | What the portal flagged | What is really there | Class |
|---|---|---|---|
| `LOCAL_CODE_HOOK_COMMAND` | command hooks | `hooks/hooks.json` declares two SessionStart command hooks: a `python3` check and `hooks/session_start.py`, which reads two environment variables by name (on Windows Python's `platform` module also looks up the processor names) and the plugin's own diagnostics, has no network call, and reads no option or credential (measured with strace and an audit hook). The second hook runs an inline program (`python3 -c`), which the public checklist itself lists as a Block ("Command path can't be followed") | blocking, portal only; the inline program is also an official Block |
| `LOCAL_CODE_MCP_SERVER` | a local MCP server | `.claude-plugin/plugin.json` `mcpServers.odoo`: `python3 server/run_stdio.py`, stdio only | blocking, portal only |
| `LOCAL_CODE_FILE_TYPE` | files outside the allowed types; no file is named | 130 of the 216 tracked files under a strict reading (7 start with `#!`, 3 are package manager files, 120 are `.py`, `.ts` or a Dockerfile); 7 under every reading (the `#!` files), 10 if the three package manager files count | blocking, portal only |
| `MCP_FORWARDS_CREDENTIAL_ENV` (10) | a credential read from the user's machine | the Odoo API key and password reach the server only from the `sensitive` options `odoo_api_key` and `odoo_password` (the pattern the portal asks for); the `odoo_url` option is not sensitive and may carry a gateway's `user:pass@`, which goes only to the user's own Odoo host (`SECURITY.md`, Basic auth in front of Odoo); seven files are tests or a build tool with fake values; `scripts/deploy_local.py` generates sandbox secrets and sends them only to `localhost` | warning (official: a hold for a reviewer) |
| `UNKNOWN_KEY` (4) | `documentationUrl`, `supportUrl`, `privacyPolicyUrl`, `termsOfServiceUrl` | directory listing fields that Claude Code ignores; validators older than Claude Code 2.1.281 warn on them | no action (official) |
| `UNKNOWN_KEY_CROSS_TOOL` | `icon` | the same kind of field | no action (official) |
| `RUNTIME_FETCH_EXEC` (4) | `CHANGELOG.md`, `docs/design/json2-online-lite.md`, `evals/README.md`, `server/tests/test_docs_surfaces.py` | the plugin runs none of the four. `docs/design/json2-online-lite.md` documents a maintainer's `git clone` and run, done by hand; `CHANGELOG.md` describes a `curl` step that was removed; the plugin's own two download-and-run flows (`/odoo-tools:deploy-local`, `/odoo-tools:odoo-setup-cli`) are user-confirmed, disclosed in `SECURITY.md`, and not among the four files. The best fit for the scanner is the standalone word `eval` (`claude plugin eval`) | documentation only, informational |
| `USES_HOOKS` | hooks exist | see above | note |
| `LOCAL_MCP_SERVER` | a local program starts an MCP server | see above | note |
| `INVENTORY_GAPS` | some components could not be listed; no file is named | two `SKILL.md` had a frontmatter that a strict YAML parser rejects (fixed, section 5); the portal's cause is not confirmed | note, real defect fixed |
| `STDIO_WEB_UNSUPPORTED` | the local server does not run on claude.ai | true (official) | note |

The portal's list for `MCP_FORWARDS_CREDENTIAL_ENV` covers only files that are new or
changed since v1.4.0, so it is not an inventory of every credential read.

## 5. What this change does

- `distribution/directory/`: the code-free edition (`odoo-tools-guide`, version
  0.1.0): a manifest, a README, two skills, one command, `SUPPORT.md`, `PRIVACY.md`,
  `NOTICE.md`, `LICENSE` and a PNG icon. About 42 KB, 10 files, all ASCII except the
  image. No hook, no server, no option, no script. The scope statement stands in the
  same words in the README, the entry skill and the command, and in short form in the
  plugin description (product rule 2), and the edition never asks for a credential
  (rule 5).
- `scripts/directory_preflight.py`: Transgenia's own preflight of a plugin folder.
  **It is not Anthropic's scanner** and a clean result is not an approval. Each
  finding names its source: the public `checklist`, the review `portal`'s text, this
  repository's `repo` rules, or Transgenia's own stricter `caution`. It never repairs
  a file. It reads a file by what it holds, not only by its name: it flags a script
  stored as a document, a hook of any type, inline shell execution and a program with
  an image name. It is a heuristic with known limits (it reads names, signatures and
  structure, so a determined author can still hide a payload in data): it exists to
  catch a mistake before the portal does, and only Anthropic's scan decides.
- `.github/workflows/ci.yml`: a `directory-edition` job that runs the preflight on
  `distribution/directory` with `--fail-on warning`.
- Tests: `server/tests/test_directory_preflight.py` (one planted violation per rule) and
  `server/tests/test_directory_preflight_gate.py` (the evasions and hostile inputs that two
  reviews found, kept as a regression list); `server/tests/test_directory_edition.py` (the
  edition, product rules 2, 3 and 5, and a calibration test: the preflight reproduces the
  portal's three blocking rules for the repository root, which is why the root cannot be
  the plugin path); `server/tests/test_skill_frontmatter.py` (every frontmatter of the
  full plugin parses for a strict reader).
- Fixes in the full plugin (Channel A), found while diagnosing:
  - `skills/odoo-mcp-tools/SKILL.md` and `skills/odoo-setup-mcp/SKILL.md`: the
    `description` had an unquoted `: ` since 1.6.0 (2026-10-30, commit `666e6ae`, which
    added two sentences that contain it), which a strict YAML parser reads as a mapping.
    Quoted, with the same text (checked with PyYAML).
  - `server/src/odoo_mcp/transport/`: a gateway password in `ODOO_URL`
    (`https://user:pass@host`) reached the model and the log in two cases: the URL held
    a character that normalizes to a reserved one (the standard parser quotes the whole
    network location in its error), or the password was written with a raw `#`, `/` or
    `?` (the parser reads the start of it as a host or a port, and `http.client` and the
    `odoo_connections` tool quote it). Such a URL is now not used and not shown: it
    fails before any request with a fixed text that says to write the character as
    `%23`, `%2F` or `%3F`, and `odoo_connections` shows `<unparseable ODOO_URL>`. A
    password in a path or a query is not a credential slot and is not covered.
    `server/tests/test_url_userinfo_leak.py` covers the three transports, the fallback
    and the server end to end (85 tests; the file cannot even be collected on the original code, and with the two new
    names stubbed 77 of the 85 fail). The test is wide on purpose: a URL with an `@` in
    its path, query or fragment and no readable `user:pass@` is refused too, because
    nothing tells it from a password cut short.
  - `docs/policy.md`: it said the hook reads the policy and connection options, true
    only until 1.5.0. It reads none since 1.5.1: as `PRIVACY.md` says, only the plugin's
    data folder and the name of the Claude app.

Effect on the root folder, which is what the live listing scans: the new script and its
tests are a tool that looks for download-and-run and credential patterns, so a lexical
scan reads their words. Transgenia's own preflight (`python3 scripts/directory_preflight.py .`
on an export of 182ace3 and of the 1.6.3 release commit) counts 9 more `LOCAL_CODE_FILE_TYPE`
errors, 13 more `RUNTIME_FETCH_EXEC` warnings and 3 more `MCP_FORWARDS_CREDENTIAL_ENV`
warnings, the same classes as for 1.6.1, and 2 `FRONTMATTER` errors fewer. The real scan may
list them. Excluding the tool and its tests from the root is a decision, not part of this change.

## 6. Checks

```bash
python3 scripts/directory_preflight.py                 # distribution/directory
python3 scripts/directory_preflight.py . --tracked     # the full plugin: fails on purpose
claude plugin validate distribution/directory --strict --profile directory
```

The preflight exits 0 when it finds nothing at the chosen level, 1 when it does, and 2
on a usage or internal error. Anthropic's `claude plugin validate --profile directory`
is a local subset of what the directory runs: it also runs a safety scan and a policy
review that the command does not. It passes v1.6.1, which the directory refused, so it
cannot be the gate either. `--strict` needs Claude Code 2.1.281 or later (older versions
warn about the directory listing fields; the edition was checked with 2.1.322, which
prints one piece of advice about an install command). The portal's own **Validate**
step runs more checks than the command (`submit.md`); whether it also applies the three
Verified-only rules is not documented.

## 7. Submitting the edition (for the product owner; not done)

1. Merge this change, so that the listing links in the manifest resolve.
2. Ask Anthropic the questions of section 8. The answers decide whether to continue.
3. In the developer portal, create a **new** submission: repository
   `Transgenia/MCP-Odoo-Tools-CE-EE-and-online`, plugin path `distribution/directory`,
   tracked branch `main`. Do not use the existing `odoo-tools` listing: its folder
   cannot be changed. Select **Validate** and read every finding before **Submit for
   review**; a validation result applies to one commit, so validate again after any push.
4. Turn off **Publish new versions automatically** until the first review is read
   (`docs/packaging.md`, release step 1).
5. The directory's own scan decides. Do not describe the edition as approved before it
   is live.

## 8. What to ask Anthropic

Contacts, all official: **Appeal this decision** on the plugin's page in the portal,
**Get help** or **Contact Anthropic** in its menu, and directory@anthropic.com (replies
can be delayed). Send no credentials and no customer data.

1. The portal refused v1.6.1 for command hooks, a local MCP server and file types, for
   an organization that is not Verified. The public checklist holds for a reviewer a hook
   or a local server command that runs a non-shell file, and blocks an inline program
   such as `python3 -c`; `publish.md` says a local MCP server is distributed in a plugin
   bundle. Which is current, and where is the rule published? Is the inline `python3 -c`
   of our second hook part of the findings?
2. What are the criteria for a Verified organization, and is there a way to be
   considered, or an exception process? The portal says there is none yet.
3. Is the file rule applied by extension, by content or both? Are `.py` files without a
   `#!` refused? Which file did the scan name for v1.6.1 (it named none)?
4. v1.4.0 has the same hook, local server and file types and is live. Will it be
   re-reviewed, or removed?
5. Is a second submission from the same repository, with plugin path
   `distribution/directory`, accepted? Is the name `odoo-tools-guide` a hold, as a
   look-alike of Transgenia's own `odoo-tools` ("Name may be confused with an existing
   listing") or because it contains the Odoo brand ("Name matches a known brand")? The
   checklist makes both holds for a reviewer.
6. A remote MCP server that Transgenia would operate: is there anything more that a
   publisher that is not Verified must meet?

## 9. Decisions for the product owner

A change that breaks a product rule needs the owner first (`docs/product-rules.md`).

1. **Name.** `odoo-tools-guide` is a proposal. A different folder is a new listing in
   any case, and a new name keeps the live `odoo-tools` listing untouched and the
   doctor of the full plugin from treating the edition as a second copy.
2. **Rule 3.** One deviation needs the owner's approval: item 1 (the synced plugin)
   cannot be met as written, because a synced copy of the edition has no tools. Item 3
   reads "the premium plan, once Transgenia hosts MCP servers": it is conditional, so
   no hosted server today is not a deviation, and the edition does not offer it. The
   draft words item 1 as a pointer to the manual, with no install command (an install
   command for a plugin the directory did not review could read as steering around its
   rules).
3. **Whether to submit before Anthropic answers question 1.** Cost: a second listing to
   maintain. Benefit: a presence in the directory for the people who install there.
4. **Whether to appeal** the refusal of v1.6.1, and with what text.
5. **Whether to list the edition in Transgenia's own marketplace** as a second plugin
   (the local validator advises an install line). It is not done here.
6. **`docs/design/json2-online-lite.md`**: an internal design record that names a
   private repository, shipped in the plugin folder. Move it out of the plugin? The same
   question now applies to `docs/directory-channel.md` and
   `docs/design/remote-mcp-threat-model.md`: `docs/` is in the release zip and the
   repository is public, so both are public. Confirm that is intended.
7. **The manual** (docs.transgenia.org, product rule 8), in Spanish, English and
   Chinese. This change alters one text a user can see, the fixed error for an
   unreadable `ODOO_URL` (it now says to write `#`, `/` and `?` of a password as `%23`,
   `%2F` and `%3F`), and corrects one sentence of `docs/policy.md` (the hook reads no
   option since 1.5.1). The manual was not open to the author of this change: check
   whether it quotes that error or repeats that sentence, and fix both. Rule 8 also
   makes the manual's PR (`software_version` set to the release, and those pages)
   a precondition of publishing the next release: it does not exist yet. When the
   edition is submitted, add pages for the two channels.
8. **The remote server**: go or no-go on the security-design review that its design
   asks for before anything is built (`docs/design/remote-mcp-threat-model.md`).
9. **Partner wording.** Confirm the tier in the Partner Hub, and whether the three public
   sentences that say "a Registered Anthropic partner" (`README.md`,
   `.claude-plugin/marketplace.json`, `skills/odoo-mcp-tools/SKILL.md`) should say
   "Registered tier of the Claude Partner Network" instead. The edition makes no
   partner claim.
10. **Texts of the edition that need the owner or counsel.** (a) `termsOfServiceUrl` points
    at `TERMS-OF-USE.en.md`, a draft for review by counsel and a convenience translation
    whose definition of the Software does not name the edition: keep it, drop the key, or
    have counsel add the edition. (b) The edition says that assisted setup is a service
    the user contracts, as the Terms of Use say of paid services: confirm that this is how
    Transgenia offers it. (c) The reference skill holds 13 verified facts and the rest of
    the edition points at the full plugin and at Transgenia's channels, which a reviewer
    may read as promotion (the policy on software that exists mainly to advertise). More
    verified reference content is the remedy; no fact that the repository does not
    already verify was added. (d) A name that leads with the brand (`transgenia-odoo-guide`)
    would avoid the look-alike and brand holds of question 5; the commands then become
    `/transgenia-odoo-guide:odoo-help`. (e) The homepage is `https://transgenia.org`
    because the product page is about the full MCP plugin.

## 10. What Transgenia can and cannot say today

Can say: the full plugin is available from Transgenia's own marketplace; the
code-free edition passes Transgenia's preflight and, with Claude Code 2.1.281 or later,
Anthropic's local validator.

Cannot say: that Anthropic approved, listed or published the edition; that Transgenia
is Verified (being at the Registered tier is not that); that a remote server exists or
works; that the preflight is equivalent to Anthropic's scanner or a guarantee against
disguise.

## 11. Sources

All fetched on 2026-11-10; check them again before relying on them.

- `https://claude.com/docs/plugins/submit.md`
- `https://claude.com/docs/plugins/pre-submission-checklist.md`
- `https://claude.com/docs/plugins/platform-support`
- `https://claude.com/docs/plugins/overview.md`
- `https://claude.com/docs/directory/publish.md`
- `https://claude.com/docs/directory/submission-status.md`
- `https://claude.com/docs/connectors/verification.md`
- `https://claude.com/docs/connectors/building/authentication` (servers with per-customer URLs)
- `https://claude.com/blog/build-plugins-for-claude`
- `https://code.claude.com/docs/en/plugins/anthropic-marketplaces.md`
- `https://support.claude.com/en/articles/17740565-manage-plugins-skills-and-connectors-from-one-plugins-page`
- `https://code.claude.com/docs/en/plugins-reference.md` (the manifest keys)
- `https://code.claude.com/docs/en/plugins/publish.md`
- `https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy`
- `https://support.claude.com/en/articles/13145338-anthropic-software-directory-terms`
- `https://www.anthropic.com/news/services-track-partner-hub`
- the review portal's Review tab for v1.6.1, checked 2026-11-08 (portal only)
