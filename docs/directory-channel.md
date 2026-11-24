# Distribution channels and Anthropic's directory

## Current directory candidate

The review of 23 November 2026 refused `b59da4d` (v1.6.4). The portal fetched 236
files from the repository root. Validation returned two notes, the directory policy
refused the version, the security scan was skipped and no reviewer action was recorded
for this commit. The previous v1.6.4 scan (`8c39c6b`) had a passing security scan.
The published version shown on the Review tab was v1.4.0 (`26de374`). The Versions
tab also records a waiting publish request for v1.3.0 (`d322cb9`).

For the v1.6.5 candidate the product owner chose the existing Odoo connector authorized
by each organization. The directory package supplies two skills and two commands.
It binds no host and installs no connector. In Cowork, the selected connector supplies
the tools and authenticates the user. The local plugin from Transgenia's marketplace
retains its server. This candidate supersedes the earlier proposal for a separate
reference-only guide described in the historical sections below.

| Portal finding at b59da4d | How the directory candidate addresses it |
|---|---|
| MCP_FORWARDS_CREDENTIAL_ENV | The package has no credential input, environment reader or process. The user signs in through their own connector. The privacy notice identifies who handles the query and the result. |
| UPDATE_ADDS_CREDENTIAL_FORWARD | The manifest declares no server, headers, options or destination that could receive an Odoo credential. The portal compares the exact candidate to its live version. |
| LOCAL_CODE_HOOK_COMMAND | The package declares and ships no hook. The user requests the connection check explicitly. |
| LOCAL_CODE_MCP_SERVER | The user's connector supplies the tool. The directory package contains no executable, server entry or launcher. |
| LOCAL_CODE_FILE_TYPE | The package inventory is pinned by a test. It consists of Markdown, a single JSON manifest, the text license and one PNG icon. |
| LOCAL_CODE_UNKNOWN_KEY | The only JSON file is the plugin manifest. The test enumerates its fields. There is no package manager, MCP or hook configuration. |
| LOCAL_CODE_NOT_READ | The old review named no unreadable file. Validate the exported root with the directory profile and inspect its component inventory. The portal must also read that commit. |
| UNREAD_ASSET_REFERENCED, ASSETS_PASSED_UNREAD | The sole image is the listing icon. Only the manifest references it. No command consumes the image. |
| UNKNOWN_KEY, UNKNOWN_KEY_CROSS_TOOL | Keep the four listing URLs and the icon. The portal explicitly describes these five fields as listing metadata that can stay. |
| RUNTIME_FETCH_EXEC, FILE_REGISTRY_REDIRECT | The directory package has no installer, package configuration, download-and-run command or instruction to fetch executable content. |
| USES_HOOKS, LOCAL_MCP_SERVER, STDIO_WEB_UNSUPPORTED | These describe the full local distribution. The directory package has no hook or local server. |
| INVENTORY_GAPS (earlier history) | Both skills and both commands must appear in the validator inventory. Directory policy and security-scan results must be read for the candidate itself. |

### Reproducing the submitted tree

The existing listing tracks the repository root. From a reviewed source commit,
use `git subtree split --prefix=distribution/directory <source-commit>` and publish
the resulting commit to the dedicated `directory/odoo-tools` branch. Compare
`git rev-parse <source-commit>:distribution/directory` with
`git rev-parse <distribution-commit>^{tree}`. They must match. Fast-forward future
updates to this branch. The directory reviews exactly what an installation receives.
The repository root on the development branch contains the full local product.

1. Run the local preflight on the directory folder with `--fail-on warning`. Run
   `claude plugin validate --profile directory --strict --json` on the exported
   plugin folder. Check the inventory, the directory findings and the incomplete flag.
2. In a Cowork task with the candidate installed, select the organization's Odoo
   connector and run `/odoo-tools:odoo-doctor`. Verify a successful read-only version
   call under that connector. With no connector, the command must explain how to
   connect and must not report a live version. Record the candidate and observed
   result without account, database or customer identifiers.
   When there is no Claude model budget, run the [offline connector scenarios in
   Codex Cloud](https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/blob/8739fd097e4028ad782b5ac3da225ccf3f21a0ec/evals/cowork-connector/README.md). Record the simulated tool calls
   separately from a run inside the Cowork application.
3. In the existing listing's Settings, changing the tracked branch starts a new
   scan. Saving the change cancels a waiting publish request. A new commit replaces
   the prior refused version for appeal purposes. Confirm this transition with the
   listing owner and record the publish setting before saving.
4. Read policy, security scan, reviewer decision and publication separately for the
   distribution commit. Record the owner's acceptance of the runtime evidence and
   Anthropic's clearance before releasing 1.6.5 through the standard workflow. Keep the development
   branch, the distribution commit, and the full release tag distinct in the record.

See Anthropic's [submission and tracked branch instructions](https://claude.com/docs/plugins/submit)
and [plugin support by app](https://claude.com/docs/plugins/platform-support).

## Historical review notes through 14 November 2026

Draft for the product owner, written on 2026-11-10 after the directory refused
v1.6.1 and updated on 2026-11-14 after it refused v1.6.3. The code-free edition has not
been submitted to Anthropic. Where a fact comes from Anthropic's
public documentation it says **official** and names the page; where it comes only
from the review portal's text for v1.6.1 or v1.6.3 it says **portal only**; the rest
is Transgenia's own reading. **Measured** marks a check that anyone can repeat on the
repository, against the portal's lists as transcribed from its review pages (section 4a);
**inferred** marks a reading that the data support but do not prove.

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

About 2026-11-10 the same check refused v1.6.3 (commit `35f0235`, the merge of the
change that section 5 describes): again "Directory policy refused this version", decided
by an automatic check, with the live version still v1.4.0 and the security scan passed.
The three blocking findings repeat and a fourth, on config file fields, is new
(section 4a). Nothing in 1.6.3 could have cleared them: they describe the product itself.

## 2. Decision

The full plugin cannot satisfy that rule and stay what it is: its value is a local MCP
server, hooks and scripts. Without a local server and hooks the product would end in this listing.
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
Transgenia. It does not connect Claude to Odoo. In claude.ai and Cowork themselves the
Odoo tools do not run: for the 91 percent of installs that come from there
(`docs/product-rules.md`, rule 1) they would need a remote MCP server, which does not
exist (`docs/design/remote-mcp-threat-model.md`). A plugin installed there also reaches
Claude Code as a synced plugin, where it runs once its options are entered (section 9,
item 14): the 91 percent are install surfaces, not a count of people who cannot use the tools.

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
   (`directory/publish.md`): the directory "checks a plugin bundle again with each new version".
   No grandfathering is promised. The announcement of 2026-09-25 said existing listings
   need no changes at that rollout (`claude.com/blog/build-plugins-for-claude`), which
   does not bind a later policy. So v1.4.0 can be re-reviewed or removed at any time.
5. **official**: "Verified" is documented as a label on directory listings. For
   connectors it means Anthropic tested the tools, and there is "no separate
   application" for it (`claude.com/docs/connectors/verification.md`,
   `directory/publish.md`). Plugin cards also show "Verified" or "Community" (support
   article 17740565, `anthropic-marketplaces.md`), with no criteria. The concept of a
   Verified organization, and the rules above (three on v1.6.1, four on v1.6.3), are
   **portal only**: no public Anthropic page states them. The public checklist is narrower: it holds for a reviewer
   a hook or a local MCP server command that runs a non-shell file the validator cannot
   read through, and any binary file other than a complete PNG, JPEG, GIF or WebP image
   or a font (it holds an `.ico`, which the portal's list allows); and it Blocks an
   inline program such as `python3 -c`
   in a hook or server command (the second hook of `hooks/hooks.json` is one, and the
   portal did not name it). The portal itself says there is no way to ask to become
   Verified yet. Anthropic does have a public article on identity and business
   verification (`support.claude.com/en/articles/14328960-identity-verification-on-claude`,
   dated 2026-08-11): it is "rolling out ... for a few use cases", asks an organization for
   its legal name, address and business registration number and a government photo ID of
   the person verifying, and does not mention plugins, the directory or a Verified label.
   Whether it is the portal's Verified is **unknown** (section 9, item 15).
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
   only once it has the Verified label (`claude.com/docs/connectors`; the rule now lives
   on `claude.com/docs/connectors/building/authentication`).

Re-read on 2026-11-14 (the pages of section 11 and others of `claude.com/docs` and
`code.claude.com/docs`, none blocked): facts 1 to 8 still hold. Fact 5
is made precise above (the checklist allows complete images and fonts, and holds an
`.ico`). Facts 9 to 13 are present in the public text today; this document did not list
them, and it cannot tell which are new since 2026-11-10.

9. **official** (`submit.md`, `pre-submission-checklist.md`): an organization can have
   one submission for each repository and folder, and up to 10 submissions in any 24
   hours (saved drafts and withdrawn submissions count). If the security scan fails a
   new version, later versions also wait until an Anthropic reviewer clears the plugin.
   The scan passed for 1.6.1 and 1.6.3, so that does not apply today, but a scan
   failure in 1.6.4 would leave a worse state than the policy refusal: keep 1.6.4 free
   of anything the scan could flag.
10. **official** (`pre-submission-checklist.md`, `platform-support`): rows that this
    document did not list. A bundled image or font may not be referred to from commands,
    hooks or scripts, nor have its path written in backticks or a code block (a hold:
    the public counterpart of `UNREAD_ASSET_REFERENCED`). `.gitattributes` export
    attributes (`export-ignore`, `export-subst`, `filter`) make validation stop. A
    top-level `bin/` makes claude.ai and Cowork refuse to install the plugin. A
    `package.json` beside a lockfile at the plugin root is held. A local server must
    start by running a plain file with plain arguments.
11. **official** (README of `github.com/anthropics/claude-plugins-community`): that
    marketplace is a read-only mirror, synced nightly from Anthropic's review pipeline,
    of plugins already approved. It is no separate route past the directory.
12. **official** (`platform-support`): hooks load in Cowork and in Claude Code, and chat
    ignores them. A local MCP server loads in Cowork "when the Cowork session runs on your
    computer", but one that references `${user_config.*}` values is "ignored when a
    referenced option has no default", and Cowork "doesn't prompt for values". This
    plugin's server references five such options. Transgenia's README (Where it works; also docs/install.md) records
    that the app reports it as `not_started` with the reason `user_config_unsupported`: that
    part is Transgenia's own observation, not Anthropic's. So Channel A reaches
    Cowork on the user's computer with its skills, commands, agents and hooks, not with the
    Odoo tools there (the 91 percent of section 2 are install surfaces: item 14 of section 9).
    `claude plugin validate
    --profile directory` exists in the CLI (checked with Claude Code 2.1.325) but the
    public CLI reference lists only `--strict` and `--json`.
13. **official** (`directory/publish.md`, `plugins/overview.md`): every
    version gets automated validation and a security scan, and "a person reviews a new
    listing before it goes live". The first version of the edition therefore gets a human
    read, unlike the automatic check that refused v1.6.1 and v1.6.3.

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
| `RUNTIME_FETCH_EXEC` (4) | `CHANGELOG.md`, `docs/design/json2-online-lite.md`, `evals/README.md`, `server/tests/test_docs_surfaces.py` | the plugin runs none of the four. `docs/design/json2-online-lite.md` documents a maintainer's `git clone` and run, done by hand; `CHANGELOG.md` describes a `curl` step that was removed; the plugin's own two download-and-run flows (`/odoo-tools:deploy-local`, `/odoo-tools:odoo-setup-cli`) are user-confirmed, disclosed in `SECURITY.md`, and not among the four files. The four are all the files that hold the whole word `eval` (`grep -iw`: an underscore joins a word) except the dotfile `.gitignore`: measured in section 4a | documentation only; a warning, not blocking |
| `USES_HOOKS` | hooks exist | see above | note |
| `LOCAL_MCP_SERVER` | a local program starts an MCP server | see above | note |
| `INVENTORY_GAPS` | some components could not be listed; no file is named | two `SKILL.md` had a frontmatter that a strict YAML parser rejects (fixed, section 5); the portal's cause is not confirmed | note, real defect fixed |
| `STDIO_WEB_UNSUPPORTED` | the local server does not run on claude.ai | true (official) | note |

The portal's list for `MCP_FORWARDS_CREDENTIAL_ENV` is not an inventory of every
credential read. All its files were new or changed since v1.4.0, but most files that name
a credential are, and the three transports that send the API key were changed since
v1.4.0 and are not listed. All 13 listed files being new or changed is unlikely by chance
among the 33 files that the preflight's credential rules flag on v1.6.3 (every tier), 26 of them new or
changed
(about 2 in 100 if listing were independent of change), but a changed file that copies the
whole environment, `scripts/sandbox_smoke.py`, is not listed, and change is confounded with
file size and with new code. So "changed since v1.4.0" is at most a necessary condition
(section 4a).

## 4a. Findings of the portal for v1.6.3

Checked about 2026-11-10 on commit `35f0235` and printed from the portal on 2026-11-13.
The decision card is the same as before: refused by an automatic check, live version
still v1.4.0, and "Escaneo de seguridad passed". What changed against section 4:

| Code | v1.6.1 | v1.6.3 | Class |
|---|---|---|---|
| `LOCAL_CODE_HOOK_COMMAND`, `LOCAL_CODE_MCP_SERVER`, `LOCAL_CODE_FILE_TYPE` | blocking | blocking, unchanged. The remedy text of the file rule is longer: it now names `.claude/skills`, a `.claude-plugin` folder that is not the plugin's own, `egress/`, `hooks.json`, `.mcp.json`, `.lsp.json` and `monitors.json` files, `output-styles/` and path characters. Still no file is named | blocking, portal only |
| `LOCAL_CODE_UNKNOWN_KEY` | absent | **new**, blocking: "Config file fields outside the allowed list". No file is named | blocking, portal only |
| `MCP_FORWARDS_CREDENTIAL_ENV` | 10 files | 13 files: the same 10, `scripts/directory_preflight.py` and its two test files | warning (official: a hold) |
| `RUNTIME_FETCH_EXEC` | 4 files | 8 files: the same 4, `docs/directory-channel.md`, `scripts/directory_preflight.py` and its two test files | documentation, tests and a developer script; a warning, not blocking: the portal says that where it only appears in documentation nothing needs to change |
| `UNREAD_ASSET_REFERENCED` | absent | **new**, 4 files: `distribution/directory/.claude-plugin/plugin.json` and the tests `test_directory_edition.py`, `test_directory_preflight.py` and `test_directory_preflight_gate.py` | warning (official: a hold) |
| `ASSETS_PASSED_UNREAD` | absent | **new**, a note: the edition's icon "passed without a code check" | note |
| `INVENTORY_GAPS` | present | gone | the frontmatter fix of 1.6.3 worked (inferred: a strict YAML reader rejects exactly the two fixed `SKILL.md` files on v1.6.1 and parses all of them on v1.6.3; the portal also changed in the same interval) |
| `UNKNOWN_KEY` (4), `UNKNOWN_KEY_CROSS_TOOL`, `USES_HOOKS`, `LOCAL_MCP_SERVER`, `STDIO_WEB_UNSUPPORTED` | listed | listed, unchanged | no action |

What is behind the changes, with the evidence and how far it goes. These readings explain
the portal's lists. None of them is used to decide what to change in the plugin: nothing is
reworded, renamed or rebuilt to move a finding (last paragraphs of this section).

- **`LOCAL_CODE_UNKNOWN_KEY`.** The only file of the tree that breaks a closed list of the
  portal's text is `cli/package.json`: `main`, `bin`, `scripts`, `dependencies` and
  `devDependencies` are outside the list for `package.json` (**measured**). The file is
  byte-identical in v1.4.0, v1.6.1 and v1.6.3, so 1.6.3 did not cause the finding, and
  the text of the same family of rules grew between the two prints: the scanner
  changed (**inferred**). That `cli/package.json` is the trigger is the leading reading
  (**inferred**, a little better than even): it is the only literal violator and the rule
  says "each package.json". It cannot be trimmed: `/odoo-tools:odoo-setup-cli` copies it
  and runs the install and the build, a CI job builds it and the release zip ships `cli/`.
  The nested edition manifest is the only config file that is new in 1.6.3 (both root manifests
  differ only in their version between the scans, and `cli/package.json` not at all), so it is the
  other candidate. It would
  count only if the portal read a nested manifest as a plain JSON file whose fields Claude Code
  does not read, and then the finding would disappear when the edition is submitted alone. It adds
  no key that the root manifest lacks and the portal's key warnings do not name it, which makes it
  the less likely of the two (**inferred**), but the data cannot rule it out. Whether the five
  listing fields
  (`documentationUrl`, `supportUrl`, `privacyPolicyUrl`, `termsOfServiceUrl`, `icon`) count
  for this blocking rule is **unknown**. The portal calls them "No action needed" and
  Anthropic's public text treats them as fields the directory reads, but the rule says
  "fields Claude Code doesn't read". It matters for Channel B, whose manifest carries the
  same five. Which file or field counted is **unknown**: the portal names none (question 7 of
  section 8). Nothing local reproduces the rule: `claude plugin validate` (Claude Code
  2.1.325) passes the root with `--strict` and the edition with `--strict --profile directory`
  (**measured**).
- **`UNREAD_ASSET_REFERENCED`.** The four files are exactly the files that contain the
  file name of the edition's icon (**measured**): the manifest field and three tests. Four
  other test files and a helper (`policy_fakes.py`) name an image, `scan.png` (the name of a
  fake attachment, not an image of the tree), and are not listed; `test_product_rules.py` and
  the preflight list image suffixes and no name, and are not listed either. So the trigger
  looks lexical: a string equal to the name of an existing image that is not an SVG
  (**inferred**: the simplest fit, not the only one. The three listed tests also walk the
  tree, but so do other `.py`, `.ts` and `.sh` files of the scanned tree (a `grep` of that
  commit finds at least 9 files that use `os.walk` or `rglob`, and more that use `glob`, `iterdir`,
  `scandir` or `listdir`), and only those 3 name the image; and a rule on
  files that are new since the previous scan fits too, which the other two lists weigh
  against, because they kept naming files that had not changed. The data cannot separate
  these). The three tests are listed because the
  edition sits inside the root plugin's folder, which is what the live listing scans; the
  edition's own manifest may be listed in any case. Scanned alone, with plugin path
  `distribution/directory`, the three tests sit outside the folder and the manifest is the
  plugin's own. The portal's text counts "a command, script, or setting in
  the plugin" that refers to an image, and `icon` is a setting, so a hold on the edition's own
  manifest is about as likely as not, unless the plugin's own icon is exempt, which is
  **unknown** (question 9 of section 8; the root manifest's SVG icon was not listed either,
  which fits both an exemption and SVG not counting as an image). It is hold-class
  (official: a hold), and the portal adds that for an organization that is not Verified "the
  file, or a command that runs it, can be refused": a refusal at review is possible in
  principle. The same text says: "If nothing runs the file, leave it as it is and the plugin stays held
  for review". Nothing runs the icon, so what is left is a hold: a reviewer may look at
  the file, and this document does not know whether the plugin's own icon is exempt.
- **`RUNTIME_FETCH_EXEC`.** Every file the portal listed, on v1.6.1 and on v1.6.3, holds the
  whole word `eval`, in any letter case (`grep -iw`: an underscore joins a word): 4 of 4 and
  8 of 8; of the 18 files added since 1.6.1 the 4 that hold the word were listed; and the only
  file of the scanned tree that holds the word and was not listed is `.gitignore`
  (**measured**). The word is the
  name of Claude Code's own `plugin eval` command (`evals/README.md`, `CHANGELOG.md`, a
  comment of `test_docs_surfaces.py`), part of a lint rule id in a design note
  (`docs/design/json2-online-lite.md`), or the detector's own pattern and fixtures (the
  preflight, its tests and this document). The plugin's real download-and-run flows (the
  image pulls of `/odoo-tools:deploy-local`, the `npm install` of `/odoo-tools:odoo-setup-cli`)
  are not listed. So the finding looks like a keyword match on documentation, tests and a
  developer script (**inferred**), and says nothing about those flows, which `SECURITY.md`
  discloses separately. Two of the eight (`evals/README.md` and the comment of
  `test_docs_surfaces.py`) hold nothing but the word, so a rule on download-and-run shapes
  alone cannot reproduce the list; the other six also hold a narrow shape. A union of the
  phrase `claude plugin eval` and such a shape fits both scans as well (a weak mechanism,
  kept as an alternative reading, section 5a). The finding is not
  blocking: the portal files it under "Other findings" and says that where it only appears in
  documentation, nothing needs to change. It states no hold, and four of the eight files are
  a script and tests, so its effect on a reviewer is unknown. The plugin runs none of the
  eight files.
- **`MCP_FORWARDS_CREDENTIAL_ENV`.** The 13 files are `server/src/odoo_mcp/config.py` (the
  product), `.claude-plugin/plugin.json` (the manifest), three scripts (two build and deploy
  tools and the preflight) and eight tests with fake values (**measured**). The three new
  files are the preflight and its two tests, which hold the detector's patterns as text:
  they read no user credential and send nothing. The manifest already does what the portal
  asks: only `odoo_api_key` and `odoo_password` are `sensitive`, and they reach the server only
  as `${user_config.KEY}` values. For `config.py` the portal now says to write the URL's host and
  port as plain text and that "until the url is written this way, every update of this plugin
  waits for a reviewer": a local server whose user chooses the Odoo host cannot do that, so it
  is a standing hold and not a change to make. The one thing that changed in how `config.py`
  relates to the senders is its import of `transport.base` (new in v1.6.3, for the URL fix),
  which loads the three transports when `config.py` is imported: it may be why the advice for
  this file became specific to the URL (**inferred**, low; a template update at the portal
  is at least as likely), and it is not something to restructure to change a scan. The manifest's
  `sensitive` options are the route of the plugin's own server; the container mode reads the
  same variables from the user's own env file. Nothing in the 10 files of
  `distribution/directory` reads the environment or a credential (**measured**), so this
  finding is not expected for the edition.

What 1.6.3 shows about this document's first version:

- Section 5 counted what the root scan would add: 9 `LOCAL_CODE_FILE_TYPE` errors, 13
  `RUNTIME_FETCH_EXEC` and 3 `MCP_FORWARDS_CREDENTIAL_ENV` warnings. Those figures came from
  Transgenia's own preflight, and the middle one was wrong: the real scan listed 4 more
  `RUNTIME_FETCH_EXEC`, 3 more `MCP_FORWARDS_CREDENTIAL_ENV` and 4 `UNREAD_ASSET_REFERENCED`.
  A preflight reports more than the portal by design; section 5 now says so.
- Section 4 called the word `eval` the best fit for `RUNTIME_FETCH_EXEC`, and said that the list
  of `MCP_FORWARDS_CREDENTIAL_ENV` covers only changed files. The first is now measured, the
  second is untested (section 4).
- `SECURITY.md` and the manual said that the download-and-run finding is about the two
  disclosed flows. It is not. `SECURITY.md` is corrected; the manual, which product rule 8
  makes part of the release, is corrected in the manual's own pull request for that release.

Two more points. The second hook's inline `python3 -c` is not named on v1.6.3 either, although
the public checklist lists an inline program in a hook command as a Block. Why is **unknown**
(question 1 of section 8). Nothing here relies on it and the hook is not changed because of it:
the rule that already refuses the plugin covers every command hook. The local `claude plugin
validate` passes the root with that hook in it, so its result says nothing about this. And a
rule for the files that the portal lists: text is removed only where a public
Anthropic rule asks for it (an image path in backticks, section 3, fact 10); otherwise accurate
documentation stays as it is even when a scan lists it, and nothing is reworded, renamed or
rebuilt to move a finding.

None of this changes the outcome. The refusal comes from the four blocking findings, and they
describe the product: a local server, hooks, scripts, and a CLI with a `package.json`. Clearing
every warning would leave the version refused, and the live listing's folder cannot change
(section 3, fact 2). The routes that can satisfy all four rules are the code-free edition
(Channel B) and Verified status, which the portal says cannot be asked for yet (section 3,
fact 5, and section 9, item 15).

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
  finding names its source: the public `checklist`, Claude Code's manifest `reference`, the
  output of `claude plugin validate` (`validator`), the review `portal`'s text, this
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
  portal's blocking rules for the repository root (three on v1.6.1, four since the review
  of v1.6.3), which is why the root cannot be the plugin path);
  `server/tests/test_skill_frontmatter.py` (every frontmatter of the
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
tests are a tool that looks for download-and-run and credential patterns, and the edition
sits inside the root, so a lexical scan reads their words. The first version of this
paragraph predicted from Transgenia's preflight 13 more `RUNTIME_FETCH_EXEC` warnings and 3
more `MCP_FORWARDS_CREDENTIAL_ENV` warnings. The real scan of v1.6.3 (section 4a) listed 4
more of the first and 3 more of the second (the script and its two tests), and it added 4
`UNREAD_ASSET_REFERENCED` and 1 `ASSETS_PASSED_UNREAD`, which come from the edition's icon.
The preflight reports more than the portal on purpose (a hold costs a review, a miss costs
a surprise) and has since been calibrated on both reviews (section 5a). Excluding the tool
and its tests from the root is a decision, not part of this change. It would change counts
only, not the outcome, and it would take away the only local gate for Channel B.

## 5a. What changed after the review of v1.6.3

Nothing that users run changes. The change is to the maintainers' tooling and to the
record.

- `scripts/directory_preflight.py` and its tests are calibrated on the two portal
  reviews. They are all the data there is, two prints of a portal whose rules changed
  between them, so a rule is a reading of both and not a copy of the portal's logic.
  New: the codes `LOCAL_CODE_UNKNOWN_KEY` (the portal's closed lists for `package.json`, a
  remote server's entry and `oauth`, and a `plugin.json` field that Claude Code does not
  read), `UNREAD_ASSET_REFERENCED`, `ASSETS_PASSED_UNREAD` and `UNKNOWN_KEY_CROSS_TOOL`; the
  clauses of the file rule on where files may sit (a `.claude-plugin` folder that is not the
  plugin's own, `.claude/skills`, `egress/`, `.mcp.json` or `hooks.json` in the wrong place,
  `output-styles/`, path characters); notes for hooks and local servers; and a credential
  rule in two tiers, a precise one (a variable named like a credential, read as a
  variable is) and a broad one (a program that touches the environment and names a
  credential) that over-reports.
- Measured on the exact commit the portal scanned (`35f0235`): the four blocking codes appear
  for the root; every file the portal listed is found (13 of 13 for
  `MCP_FORWARDS_CREDENTIAL_ENV`, 8 of 8 for `RUNTIME_FETCH_EXEC` as a note on the word `eval`,
  and exactly the 4 `UNREAD_ASSET_REFERENCED` and the 1 `ASSETS_PASSED_UNREAD`); and it reports
  20 files more for the credential code that the portal did not list, and 7 more
  `RUNTIME_FETCH_EXEC` warnings (the pattern of an image pull or a package run, which the
  portal never listed). The edition folder has no error and no warning. The lists are in
  `server/tests/test_directory_edition.py`, whose recall test exports that commit with
  `git archive` and is skipped in a shallow clone (the server job of CI fetches the full
  history).
- These recalls are **in-sample**, not predictions. The credential and asset rules were fitted
  after the lists were seen, and only the word `eval` was fitted on v1.6.1 and then held on
  v1.6.3 (8 of 8). The credential list is separated by file size about as well as by the
  environment term, since the three new files that the portal listed are also the three
  largest new code files, so that rule is a net and not a mechanism. The edition's clean
  report rests on one assumption: that the plugin's own icon is not held. The preflight
  reports it as a note (`UNREAD_ASSET_REFERENCED`, severity info), so that if the portal does
  hold the edition for it, the note is the line to look at.
- `SECURITY.md`: the download-and-run finding is described as what it lists, the two real flows
  as a separate disclosure, and the credential bullets name the files the portal listed (the tests as a folder).
- This document: sections 3, 4, 4a and 5, and the questions and decisions of sections 8 and 9.

A prediction for the next scan of the root, written down before it happens so that it can
be wrong. It is for the text of the repository as it is when it is written: a later edit of a
file voids the part about that file.

- The same four blocking findings.
- `MCP_FORWARDS_CREDENTIAL_ENV`: 13 files, or 14 if `server/tests/test_directory_edition.py` is
  listed too. It now reads the `CI` variable and names a credential, so the preflight flags it
  in its broad tier, which already flagged 16 files that the portal did not list on v1.6.3 (20
  counting every tier). Either count fits section 4a, and neither separates its readings.
- `RUNTIME_FETCH_EXEC`: 9, the 8 of v1.6.3 and `SECURITY.md`, which now holds the word `eval`.
  8 would mean that the trigger is narrower than the word.
- `UNREAD_ASSET_REFERENCED`: the same 4, and up to 2 more that now name the edition's icon
  (`icon.png`): `scripts/directory_preflight.py` in a docstring, as an example of a file name, and
  this document in this line. The preflight lists both, and nothing in either is worded to avoid
  it. `ASSETS_PASSED_UNREAD`: the same 1.

The 13-or-14 split cannot tell the readings of section 4a apart: the preflight flags 33 files for this
code on v1.6.3 (24 of them in its broad tier) and the portal listed 13 of the 33, so one more flagged
file says little. The icon line can: 6 would support a lexical match in any text file (a Markdown document and a docstring are both
counted), 4 would count against it or mean that the portal changed, and 5 would split the script
from the prose.

A result outside these means that a reading of section 4a is wrong or that the portal changed
again.

## 6. Checks

```bash
python3 scripts/directory_preflight.py                 # distribution/directory
python3 scripts/directory_preflight.py . --tracked     # the full plugin: fails on purpose
claude plugin validate distribution/directory --strict --profile directory
```

The preflight exits 0 when it finds nothing at the chosen level, 1 when it does, and 2
on a usage or internal error. Anthropic's `claude plugin validate --profile directory`
is a local subset of what the directory runs: it also runs a safety scan and a policy
review that the command does not. It passes v1.6.1 and v1.6.3, which the directory
refused, so it cannot be the gate either. `--strict` needs Claude Code 2.1.281 or later
(older versions warn about the directory listing fields; the edition was checked with
2.1.322 and with 2.1.325, which print one piece of advice about an install command). The
portal's own **Validate** step runs more checks than the command (`submit.md`); whether
it also applies the four Verified-only rules is not documented. The flag
`--profile directory` is not in the public CLI reference.

## 7. Submitting the edition (for the product owner; not done)

1. The edition's files, and the links of its manifest, are already in the repository (v1.6.3):
   check that each link resolves before the first save.
2. Ask Anthropic the questions of section 8. The answers decide whether to continue.
3. Before the day of the submission: the organization's GitHub connection on claude.ai needs
   push access to the repository, and the person who submits needs the Owner role on a Team
   plan (`directory/publish.md`; `submit.md` for the rest). The portal also asks a data handling step (four questions) and a
   compliance step (a contact e-mail and four acknowledgements): read them first.
4. In the developer portal, create a **new** submission: repository
   `Transgenia/MCP-Odoo-Tools-CE-EE-and-online`, plugin path `distribution/directory`. Track a
   **tag**, not `main` (for example `edition-0.1.0`): `submit.md` says that a tag stays on its
   commit until the tag is changed, so the scanned commit is the one that was checked, and
   merges of 1.6.x to `main` do not produce edition versions. Do not use the existing
   `odoo-tools` listing: its folder cannot be changed. Select **Validate** and read every
   finding before **Submit for review**; a validation result applies to one commit, so
   validate again after any change. Settle before the first save of any form what is hard or
   impossible to change: the repository and the plugin path (`submit.md`: they cannot change
   after a submission), the icon (Claude Code 2.1.325 says the first saved icon may become the
   listing icon only once; it advises a square PNG of 512 to 2048 pixels) and the name (a
   rename changes the slash-command prefix that users have learned; the display name does
   not). The tracked
   tag can be changed later on the Settings tab, but not while the plugin is with a reviewer. Section 9, item 12, describes a
   probe to run first in a scratch repository.
5. Raise the edition's `version` (0.1.0 today) with every change to its files: `submit.md`
   asks to raise it with every release, and nothing in CI forces it.
6. The default is that a reviewer publishes each version, and a person reviews a new listing
   before it goes live. Keep **Publish new versions automatically** off until the first review
   is read (`docs/packaging.md`, release step 1). The checklist says that the scan can raise
   the same hold again on each new version, so an update may wait for a reviewer too.
7. The directory's own scan decides. Do not describe the edition as approved before it
   is live.

## 8. What to ask Anthropic

Contacts, all official: **Appeal this decision** on the plugin's page in the portal
(the v1.6.1 print shows only **Editar** and **Check for new commits**, so it is probably
not offered for a published listing), **Get help** or **Contact Anthropic** in its menu,
and directory@anthropic.com (replies can be delayed). Anthropic's text asks to include
the listing's name, the organization the plugin was submitted from and the status the
portal shows. Send no credentials and no customer data.

1. The portal refused v1.6.1 for command hooks, a local MCP server and file types, for
   an organization that is not Verified. The public checklist holds for a reviewer a hook
   or a local server command that runs a non-shell file, and blocks an inline program
   such as `python3 -c`; `publish.md` says a local MCP server is distributed in a plugin
   bundle. Which is current, and where is the rule published? Which of our two hook
   commands does the finding name?
2. Does Anthropic's policy describe any route, other than Verified status, by which a plugin
   that runs a local server is listed? The portal says only Verified organizations may use these
   and that there is no way to ask yet; `publish.md` says that there is no separate application
   for the label and that Anthropic decides during review. Is the portal's Verified the identity
   and business verification of Anthropic's public article (support article 14328960), and can an
   organization start it?
3. Is the file rule published, with the types that it accepts? Which file did the scan name
   for v1.6.1 (it named none)?
4. v1.4.0 has the same hook, local server and file types and is live. Will it be
   re-reviewed, or removed?
5. Is a second submission from the same repository, with plugin path
   `distribution/directory`, accepted? Is the name `odoo-tools-guide` a hold, as a
   look-alike of Transgenia's own `odoo-tools` ("Name may be confused with an existing
   listing") or because it contains the Odoo brand ("Name matches a known brand")? The
   checklist makes both holds for a reviewer.
6. A remote MCP server that Transgenia would operate: is there anything more that a
   publisher that is not Verified must meet?

Added after the review of v1.6.3 (section 4a):

7. `LOCAL_CODE_UNKNOWN_KEY` names no file. Which file or field counted? `cli/package.json`
   (`main`, `bin`, `scripts`, `dependencies`, `devDependencies`) is the one that fits the
   portal's list: is it the one? Do the five listing fields (`documentationUrl`,
   `supportUrl`, `privacyPolicyUrl`, `termsOfServiceUrl`, `icon`) count under this rule?
8. `RUNTIME_FETCH_EXEC` lists files that hold the word eval (the documentation of Claude
   Code's own `plugin eval` command, a lint rule id, and tests and a script of ours) and not
   the flows that do download and run code. Is that intended? If not, this is a report of a
   false positive.
9. `UNREAD_ASSET_REFERENCED` listed the four files that contain the name of the edition's
   icon, among them the edition's own manifest. Does the icon that the plugin's own manifest
   names count under this rule, since the public text asks authors to set one? Is an SVG
   text or an image for this rule and for the file-type rule? Is the listing icon read only
   the first time it is saved? Where does Anthropic want the icon: in `.claude-plugin/`,
   which the validator and the portal accept, or at the plugin root, where the plugin
   reference puts every file but the manifest (its example is `./logo.png`)?
10. Does a `.claude-plugin` folder inside the plugin folder (the edition, in the scan of the
    repository root) count under "each .claude-plugin folder but the plugin's own"?
11. `MCP_FORWARDS_CREDENTIAL_ENV` for `config.py` now says that every update waits for a
    reviewer until the URL's host and port are written as plain text. Can that hold be
    cleared for a local server whose user chooses the Odoo host, and when does the
    "Verified organizations only" placement of `${user_config.KEY}` in a server's
    environment apply?
12. The portal has said since at least 2026-11-09: "Publish requested for a newer version.
    An Anthropic reviewer makes it live; the request is waiting for them." For which
    version is that request, and is it stale? The portal's Versions tab should say. A publish
    request is offered for a version that passed the checks, so it is probably not for v1.6.1
    or v1.6.3 (**inferred**). Which one it is, is unknown: a version that passed, or one held
    earlier that a reviewer cleared.

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
   option since 1.5.1). The manual's branch for the next release carries what rule 8 asks
   (`software_version`, the live image pins and the security page, in three languages); its
   pull request is a precondition of publishing, and is merged after the release is
   published. When the edition is submitted, add pages for the two channels.
8. **The remote server**: go or no-go on the security-design review that its design
   asks for before anything is built (`docs/design/remote-mcp-threat-model.md`).
9. **Partner wording.** Confirm the tier in the Partner Hub, and whether the three public
   sentences that say "a Registered Anthropic partner" (`README.md`,
   `.claude-plugin/marketplace.json`, `skills/odoo-mcp-tools/SKILL.md`) should say
   "Registered tier of the Claude Partner Network" instead. The edition's ten files make no
   partner claim, but its `documentationUrl` opens the manual's page of the plugin
   (`docs/odoo-tools/index.en.md` of the manual repository), which says "registered partner of
   Anthropic (Registered tier)" and "neither a certified nor a first-party product of
   Anthropic". Anthropic's Terms, read second-hand and not in full, forbid statements that
   suggest a partnership with Anthropic without its prior written approval: confirm the
   wording before submitting.
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

Added after the review of v1.6.3 (section 4a):

11. **The portal's documentation links.** Open the three **Documentación** links of the
    review (`MCP_FORWARDS_CREDENTIAL_ENV`, `UNKNOWN_KEY`, `UNKNOWN_KEY_CROSS_TOOL`) and
    record the page and anchor each one opens. A few minutes; it settles which public
    page backs each code, which a reading of the text could only guess. While there, the
    **Versions** tab lists each scanned commit with the result of its checks (`submit.md`):
    read the credential finding of v1.4.1 and v1.5.0. `config.py` and `scripts/deploy_local.py`
    had not changed since the live version at v1.4.1 (nor had `deploy_local.py` at v1.5.0). A
    list that names them shows that the finding does not cover only the files that changed;
    a list limited to the files that did change supports the opposite reading.
12. **Probe the portal's Validate step before any real submission, knowing what it can
    answer.** The two unknowns that decide whether Channel B can pass as designed (the five
    listing fields and the edition's own icon, section 4a) cannot be settled locally. The probe
    can speak, at most, to the icon and to whether **Validate** runs the Verified-only rules at
    all; the five fields stay a question to Anthropic (section 8, question 7). The
    public checklist (read 2026-11-14) says that **Validate** "runs every check in this
    page's tables" and that a scan runs after the submission on each new commit. None of
    those tables holds a Verified-only rule, and the review of v1.6.3 lists "Validación has
    warnings" and "Directory policy failed" as two separate checks. So **Validate** probably
    does not run the four blocking rules, and a clean result for the edition proves nothing
    about them (inferred, not measured). What the tables do
    hold, and **Validate** should therefore report, is the image row (a bundled image is not
    named from a command, a hook or a script, and its path is not written in backticks or a
    code block: a hold) and the spelling of the component keys. The tables are not the portal's
    whole list (they hold no unknown-field check and no row on a download piped to a shell), so a Validate
    that reports fewer codes than the review did does not show which of them it runs. In a scratch public repository, never
    in the real submission and never with **Submit for review**, use a plugin name that is
    not the real one and the flow that the portal documents (push a commit, select
    **Validate**, push the next commit, select **Re-validate** on the **Source** step of the
    same form): first the edition as it is (does **Validate** report the icon?); then, if you
    want a positive control, the same with a `package.json` that holds `scripts` and
    `dependencies` (does `LOCAL_CODE_UNKNOWN_KEY` appear?). Taking the five listing fields out of the
    manifest is not part of the probe: it would be a change made to learn what a rule counts, and
    question 7 asks Anthropic whether they count. A second draft of the same repository with the whole repository as
    the plugin path is the control: it should show the four blocking rules of the real
    review, and if it does not, **Validate** does not run them and the other drafts say
    nothing about them. Tell Anthropic before that the probes will run, delete the drafts
    afterwards, and tell Anthropic that they were deleted. Do not iterate variants to find the smallest wording or structure
    that passes: that would be a search for what the scanner misses, and the point is only
    to measure. Limits: drafts count toward the 10 submissions of any 24 hours, and the
    listing icon may be taken the first time a form is saved (`claude plugin validate` of
    Claude Code 2.1.325 says so), which is why the real edition's form is opened only when
    its icon is final. A scan of a real commit is the only certain reading of the policy
    rules, and it leaves a record that reviewers see; a test commit on the branch that the
    live listing tracks touches what Channel A users may install, so it is the owner's
    decision and is disclosed to Anthropic.
13. **`odoo_url` and gateway credentials.** `odoo_url` is not `sensitive`, although the
    server treats a `user:pass@` in it as a secret and `SECURITY.md` says that a gateway
    password written there is stored in plain plugin settings. Options: make `odoo_url`
    `sensitive` (how Claude Code treats a saved value when the flag changes is not
    verified, and the plugin's own options check, `install_check.py`, reads no sensitive
    value, so it would report `odoo_url` as missing for a fully configured copy), or add
    separate sensitive options for the gateway user and password and keep
    the URL free of credentials, which also ends the class of problem that the 1.6.3 fix
    handles. Either is a feature release, changes the manual (rule 8), and does not change
    the portal's finding. It is not part of 1.6.4.
14. **What the live listing serves.** The directory serves v1.4.0 to everyone who installs
    from it. v1.6.1 and v1.6.3 were refused (sections 4 and 4a), v1.4.1 and v1.5.0 were held for
    a reviewer (section 1: a hold, not a refusal), and this document records nothing for v1.5.1
    and v1.6.0 (the Versions tab may show it). That copy has no permission
    policy (the module that 1.5.0 added does not exist in it): by default it lists all 28
    tools, the 9 that write among them, with no profile, no redaction of results and no audit
    log, and its `odoo_connections` tool returns a `user:pass@` of the Odoo URL as written,
    which the doctor of that version calls. 1.5.0 fixed these; 1.6.3 closed further ways in which a gateway password could
    appear (`CHANGELOG.md`). What
    the Odoo user's own rights allow still bounds all of it, the plugin advises a
    least-privilege user, and the repository records at least two support cases on the directory's
    1.4.0 and no loss of data or exposure of a secret. The code runs only in Claude Code, for
    people who entered options there. claude.ai and Cowork themselves run no Odoo tools
    (README), but a plugin installed on a claude.ai account also appears in Claude Code as a
    synced plugin at the next session start (`platform-support`) and runs there once its
    options are entered, so the share of installs made in Claude Code (8.6 percent) understates
    the people who run the server: an install made elsewhere can run it once synced. The
    absolute number is in the portal's Usage tab. The live version would itself be refused if it were submitted today
    (**inferred**, medium: it rests on the portal's text, and the public checklist and
    `publish.md` state no such rule), so leaving it as it is and asking for an update are not
    symmetric choices. The CLI fallback has no permission policy in any version
    (`SECURITY.md`), so a newer MCP server does not close that route. Options, all within the
    owner's reach: leave it; ask Anthropic which version the waiting publish request is for
    (section 8, question 12) and whether v1.4.0 will be re-reviewed or removed (question 4); delist the plugin (**Delist plugin** in the menu of its page: people who already installed
    it stop getting updates and their copy may be removed, and relisting is a request that
    can be declined: `submit.md`); and, whichever is
    chosen, publish a notice on channels that Transgenia controls: `SECURITY.md` and the README
    once their text carries it, the manual (once a release carries it, in Spanish, English and Chinese), direct contact with
    assisted-setup customers, or a pinned Discussion or issue. Not a GitHub Release, because
    publishing one starts this repository's release workflow (`release: published`), and not a
    security advisory, which is a formal vulnerability record and the owner's own decision. The
    notice says what a 1.4.x user can do today: remove the directory's copy first, so as not
    to run two (a copy synced from claude.ai is listed as `<name>@synced` and is removed on claude.ai, from
    Customize > Plugins, by turning it off or selecting **Remove** in its menu, as `overview.md`
    and `discover-plugins.md` say, which was not run on a real account; a copy installed with the
    CLI is removed with `claude plugin uninstall` at the scope that its `claude plugin list --json`
    entry shows, from that project's folder for project or local scope, and a project-scope copy
    is recorded in the project's shared `.claude/settings.json`), and install one copy from
    Transgenia's marketplace; until then, use a
    least-privilege Odoo user with an expiring key, turn on Read-only mode (in v1.4.0 the 9 write
    tools stay listed and are refused when called, before Odoo is touched; from 1.5.0 they are
    not listed either. It stops neither a read of a stored secret nor the `odoo_connections`
    echo), and
    keep `user:pass@` out of the Odoo URL, changing that password if it was used. The plugin
    cannot carry that notice: it sends nothing to Transgenia by design. A copy from
    Transgenia's marketplace added from the command line is not updated by itself (Claude Code
    turns auto-update on by default only for official marketplaces and for marketplaces added
    from claude.ai): it needs `claude plugin marketplace update transgenia-odoo-tools` and
    `claude plugin update odoo-tools@transgenia-odoo-tools --scope <scope>`, which
    `/odoo-tools:odoo-doctor` prints in full. Versions 1.5.0 and 1.5.1 also had a bypass of the policy for a context passed
    positionally on Odoo 10 to 12, closed in 1.5.1 and 1.6.0 except one narrow case (known limit 10 of `docs/policy.md`, repeated
    in the Known limits of `SECURITY.md`; `CHANGELOG.md`).
15. **Two checks in the portal and the organization's settings.** (a) Open the **Versiones**
    (Versions) tab and read which version the waiting "Publish requested" request is for (section 8,
    question 12). If a reviewer clears an older version, it can go live at any time and
    outside Transgenia's control: v1.5.0 would give directory users the permission policy,
    v1.4.1 would not. `submit.md` says that the directory cancels a waiting publish request when the tracked
    branch or tag changes, and that the branch or tag cannot be changed while the plugin is
    with a reviewer; what a
    reviewer would release instead is unknown, so it is not proposed here. (b) Look in the organization's settings and in the portal for an
    identity and business verification prompt (section 3, fact 5). Whether it is what the
    portal calls Verified is unknown. If a prompt exists, the person whose government ID is
    asked for completes it in Anthropic's own flow; no document, number or credential goes
    through a conversation with Claude. Until Anthropic says so, Transgenia is not Verified
    and is not described as such.

## 10. What Transgenia can and cannot say today

Can say: the full plugin is available from Transgenia's own marketplace; the code-free
edition passes Transgenia's preflight and the local command `claude plugin validate` of
Claude Code 2.1.281 or later, which is a subset of what the directory runs (it also passes
the full plugin, which the directory refused). That is not an approval.

Cannot say: that Anthropic approved, listed or published the edition; that Transgenia
is Verified (being at the Registered tier is not that); that a remote server exists or
works; that the preflight is equivalent to Anthropic's scanner or a guarantee against
disguise.

## 11. Sources

All fetched on 2026-11-10 and read again on 2026-11-14, together with other pages of
`claude.com/docs` and `code.claude.com/docs` (none blocked). They carry no date, so check
them again before relying on them.

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
- `https://github.com/anthropics/claude-plugins-community` (the nightly mirror)
- `https://code.claude.com/docs/en/plugins/cli-reference`,
  `https://code.claude.com/docs/en/plugins/loading`, `https://code.claude.com/docs/en/discover-plugins.md`
  (the defaults of auto-update) and the support article 14328960 on identity and business
  verification
- the review portal's Review tab for v1.6.1, checked 2026-11-08 (portal only)
- the review portal's Review tab for v1.6.3, checked about 2026-11-10 and printed on
  2026-11-13 (portal only; the print has no text layer, so its text was read from the images)
