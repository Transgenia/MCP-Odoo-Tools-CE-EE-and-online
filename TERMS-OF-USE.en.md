> **Note (not part of the legal text):** draft for review by counsel; not legal advice.
>
> **Convenience translation.** The Spanish version (`TERMS-OF-USE.es.md` and
> `Terminos-de-uso-odoo-tools-v2.0-2026-09.docx`) is the only legally binding text. In case of any
> discrepancy between this translation and the Spanish version, the Spanish version prevails.

# TERMS OF USE

**OF ODOO-TOOLS (FREE EDITION) OF CENTRUM TRANSGENIA SAS (TRANSGENIA.ORG)**

**Version 2.0 – Issue date: September 2026**

These Terms of Use (the **“Terms”**) set out the conditions under which Centrum Transgenia SAS (**“Transgenia.org”** or **“Transgenia”**) makes the free edition of odoo-tools, and the related services described below, available to any individual or legal entity that downloads, installs or uses it (the **“User”**). The Software is distributed under the **MIT License**. These Terms complement that license and never restrict it: they govern the User's relationship with Transgenia.org regarding trademarks, support, privacy and data processing, third-party licenses, use of Transgenia.org's channels and repositories, and governing law.

---

## 1. PURPOSE AND SCOPE

### 1.1 The Software

- **“The Software”** means the free edition of odoo-tools published by Transgenia.org in the public GitHub repository Transgenia/MCP-Odoo-Tools-CE-EE-and-online, which comprises:
  - (a) the odoo-tools plugin for Claude Code;
  - (b) the `odoo-mcp-tools` MCP server, also published on PyPI;
  - (c) the fallback command-line interface (CLI);
  - (d) the tools that create a local test environment (sandbox) with Odoo Community Edition, versions 10.0 to 19.0 (the Odoo and PostgreSQL images those tools download are governed by section 4.1);
  - (e) the container image `ghcr.io/transgenia/odoo-mcp-tools` (the third-party components included in the image, such as the base operating system and the Python interpreter, keep their own licenses); and
  - (f) its documentation, skills, commands, agents and hooks.
- **“The Services”** means the public repository and its issue tracker, the documentation published by Transgenia.org, the official contact channels listed in section 14, and any free support that Transgenia.org provides in connection with the Software.

### 1.2 Free of charge; other editions

- The Software and the Services described in these Terms are offered free of charge.
- The premium edition (odoo-tools premium, which includes the `odoo-tools-lsp` language server) is a separate, closed-source product governed by its own End User License Agreement (EULA) and by the **Commercial Master Agreement (Contrato Comercial Macro)** that the customer enters into with Transgenia.org. These Terms grant no rights to the premium edition. Access to the premium edition is granted only on request sent to Transgenia.org by email or WhatsApp (section 14), under its EULA.

### 1.3 What is not included

- Transgenia.org does not provide instances, licenses or subscriptions of Odoo Enterprise Edition or Odoo Online, which are products of Odoo S.A. The local test environment includes Odoo Community Edition only. To use the Software with Odoo Enterprise Edition or Odoo Online, the User must connect their own, properly licensed instance.
- Transgenia.org does not host, operate or back up the User's Odoo instance or its data.

---

## 2. RELATIONSHIP WITH THE MIT LICENSE

### 2.1 License of the Software

- The Software is licensed under the MIT License, whose text is included in the repository's `LICENSE` file. That license permits anyone to use, copy, modify, merge, publish, distribute, sublicense and sell copies of the Software, provided that the copyright notice and the permission notice are included in all copies or substantial portions of the Software.

### 2.2 The MIT License prevails

- In everything relating to the Software, **the MIT License prevails over any provision of these Terms**. No provision of these Terms limits, conditions, suspends or revokes the rights granted by the MIT License, or adds conditions to their exercise.
- If any provision of these Terms could be read as a restriction on using, copying, modifying or distributing the Software, that provision shall be understood to refer exclusively to the Services and to the User's relationship with Transgenia.org.

### 2.3 Matters governed by these Terms

- These Terms govern only: use of Transgenia.org's trademarks; support and the Services; privacy and data processing; the relationship with third-party licenses and services; acceptable use of the Services; and governing law and jurisdiction.

---

## 3. INTELLECTUAL PROPERTY AND TRADEMARKS

### 3.1 Copyright

- Copyright in the Software belongs to Transgenia.org and, as to their contributions, to the third-party authors identified in the repository's `NOTICE` file (including the components reused from the odoo-agent project, published under the MIT License) and to the other contributors, as shown by the repository history.
- The MIT License is a non-exclusive license and does not assign or transfer the economic rights of the copyright.

### 3.2 Transgenia.org trademarks

- The names “Transgenia” and “Transgenia.org”, their logos and other distinctive signs belong to Transgenia.org and are protected under the Federal Law for the Protection of Industrial Property (Ley Federal de Protección a la Propiedad Industrial, LFPPI). The MIT License grants no rights to them.
- Anyone who modifies or redistributes the Software must keep the copyright notice required by the MIT License and may truthfully state that their version is derived from Transgenia.org's odoo-tools. Without Transgenia.org's prior written permission, they may not use those trademarks in a way that suggests that their version is the official one, that Transgenia.org endorses it, or that Transgenia.org supports it.

### 3.3 Third-party trademarks

- “Odoo” is a trademark of Odoo S.A. The Software is an independent tool, not affiliated with or endorsed by Odoo S.A., and mentions that trademark only to identify the platform it works with.
- “Claude” and “Claude Code” are trademarks of Anthropic, PBC. Other trademarks mentioned (GitHub, PyPI and Docker, among others) belong to their respective owners.

### 3.4 Contributions

- Contributions that the User submits to the public repository (pull requests, patches or documentation) are accepted under the MIT License, as stated in `CONTRIBUTING.md`. By submitting them, the User represents that they have the right to contribute them under that license and that they contain no code taken from projects under incompatible licenses, in particular AGPL-licensed projects.

---

## 4. THIRD-PARTY LICENSES AND SERVICES

### 4.1 Odoo Community Edition

- Odoo Community Edition is distributed under the GNU Lesser General Public License, version 3 (LGPL-3). The local test environment downloads container images of Odoo Community Edition and PostgreSQL (mirrors of the official images, published on `ghcr.io/transgenia`, with Docker Hub as fallback), which are governed by their own licenses: LGPL-3 and the PostgreSQL License, respectively.

### 4.2 Odoo Enterprise Edition

- Odoo Enterprise Edition is licensed by Odoo S.A. under the Odoo Enterprise Edition License v1.0 and requires a current subscription with Odoo S.A. or one of its authorized partners. Holding and complying with that license is the User's sole responsibility.

### 4.3 Odoo Online

- Odoo Online is Odoo S.A.'s cloud service (SaaS) and is governed by the terms of service and subscription that the User has accepted with Odoo S.A. To use the Software with Odoo Online, the subscribed plan must include external API access. Verifying that access and complying with those terms is the User's responsibility.

### 4.4 Other components

- The Software includes or may use other components under their own licenses, in particular the npm dependencies installed by the fallback CLI, the Python dependencies of the MCP server and the optional Python packages that the User chooses to install. Those licenses are stated in each component's metadata and documentation; the `NOTICE` file identifies the third-party code incorporated into the repository. Nothing in these Terms limits the rights those licenses grant.

### 4.5 MCP client and AI model provider

- The Software runs inside the MCP client chosen by the User (for example, Claude Code). Tool results are returned to that client and, through it, to the User's AI model provider (for example, Anthropic). That processing is governed by the terms the User has with those providers; Transgenia.org is not a party to those agreements.

### 4.6 Compatibility

- Transgenia.org does not guarantee that the Software will remain compatible with future Odoo versions or with interface changes or removals announced by Odoo S.A., such as the XML-RPC and JSON-RPC endpoints.

---

## 5. PRIVACY, CREDENTIALS AND TELEMETRY

### 5.1 Local execution

- The Software runs on the User's machine or on infrastructure the User controls. Transgenia.org operates no server for the Software and receives, proxies and retains no data from it: no credentials, no Odoo records and no prompts.
- Downloading the Software and the container images from GitHub, PyPI, ghcr.io or Docker Hub is governed by the terms and privacy policies of those platforms.

### 5.2 Credentials

- Odoo credentials (URL, database, login and API key or password) are entered as plugin options in Claude Code. The API key and the password are stored as sensitive options in Claude Code's credential store: the operating system keychain where available (for example, the macOS Keychain) or, otherwise, a local credentials file restricted to the User's account.
- Credentials are sent only to the Odoo instance the User configures. **Transgenia.org never receives them.**
- Some optional features store credentials or passwords in local configuration files (`.env`) created on the User's machine with owner-only permissions: the fallback CLI, the local test environment and the container mode. Protecting those files, and deleting them when no longer used, is the User's responsibility.
- If the User deploys the MCP server in HTTP mode, credentials travel in the headers of each request to the server that the User operates. Protecting that server (for example, with TLS and access control) is the User's responsibility.
- Transgenia.org will never ask for the User's Odoo password or API key by chat, email, WhatsApp or any other channel. When a contracted service requires access to the User's Odoo instance, access will be through a dedicated user, created and revocable by the User, under the Commercial Master Agreement.

### 5.3 Data queried in Odoo

- When the User or their AI agent requests it, the Software reads and, if the User allows it, modifies records in the User's Odoo instance, which may contain personal data. The Software keeps no copy of its own of that data: it returns it to the MCP client, which sends it to the model provider as described in section 4.5.
- For that data, the User (or the organization the User represents) acts as data controller. Transgenia.org has no access to it. Using a least-privilege Odoo user and enabling read-only mode for exploration tasks is recommended.

### 5.4 Optional telemetry (opt-in)

- Telemetry is **disabled by default**. It is enabled only if the User explicitly turns it on (`ODOO_TELEMETRY=opt-in`).
- Even when enabled, the Software sends nothing by itself: it renders on screen a report free of personal data that the User reviews and, if they so decide, shares manually. The report is limited to aggregated technical data: plugin version, Odoo version and edition, deployment type, transport and per-tool usage counters.
- The report never includes the URL, database name, login, email address, secrets, company or customer names, record contents, file paths or host names.
- The optional observability endpoints (OpenTelemetry and Prometheus) send data only to collectors that the User configures, never to Transgenia.org.

### 5.5 Data that Transgenia.org does receive

- Transgenia.org receives only the data that the User voluntarily provides when contacting it through its official channels, opening an issue or contracting services. That data is processed under Transgenia.org's Privacy Notice, available at <https://transgenia.org/legal-privacidad.html> (English: <https://transgenia.org/en/legal-privacy.html>).
- Issues in the public repository are visible to anyone. The User must not post credentials, personal data or confidential information about their Odoo instance in them.

---

## 6. PERSONAL DATA PROTECTION

### 6.1 Users in the European Union (GDPR compliance)

- Where the User is located in the European Union or processes data of people located there, each party shall comply, to the extent applicable to it, with Regulation (EU) 2016/679, the General Data Protection Regulation (GDPR).
- Because Transgenia.org has no access to the data that the User processes with the Software, it does not act as a processor of that data. If the User contracts services in which Transgenia.org does access personal data on the User's behalf, the parties shall enter into the corresponding Data Processing Agreement (DPA) under Article 28 GDPR.
- For data that Transgenia.org receives as controller (section 5.5), data subjects may exercise their rights of access, rectification, erasure, restriction of processing, portability and objection through the means listed in section 6.2.

### 6.2 Users in Mexico (Federal Law on the Protection of Personal Data Held by Private Parties)

- Transgenia.org and the User, each as applicable, shall comply with the Federal Law on the Protection of Personal Data Held by Private Parties (LFPDPPP), published in the Official Gazette of the Federation (DOF) on 20 March 2025, which repealed the 2010 law of the same name, and the regulations derived from it, when processing personal data of data subjects in Mexico.
- The processing of the personal data that Transgenia.org receives is described in its Privacy Notice (<https://transgenia.org/legal-privacidad.html>), which these Terms do not reproduce and which prevails on that subject. ARCO rights (Access, Rectification, Cancellation and Opposition) are exercised by request sent to notificaciones@transgenia.org. The address dev@transgenia.org is reserved for technical matters.
- If the User stores or queries personal data in their Odoo instance through the Software, the User does so under their sole responsibility as data controller and must have the privacy notices, the consent or other legal basis required, and the security measures required by law.

### 6.3 Data deletion requests (right to erasure)

- Any data subject (in Mexico, the European Union or any other jurisdiction) may request the erasure of personal data held by Transgenia.org under the law applicable to them, by writing to notificaciones@transgenia.org.
- Transgenia.org shall handle those requests without undue delay, provided that the requester proves their identity and standing and that no legal obligation prevents the erasure.
- Requests concerning data stored in the User's Odoo instance must be addressed to the User, as data controller, since Transgenia.org has no access to that data.

---

## 7. COPYRIGHT: THE MEXICAN FEDERAL COPYRIGHT LAW AND THE DMCA

### 7.1 Federal Copyright Law (Mexico) and INDAUTOR

- The Software is a computer program and, as such, a work protected by the Federal Copyright Law (Ley Federal del Derecho de Autor, LFDA) on the same terms as literary works (articles 13, section XI, 101 and 102).
- The LFDA distinguishes moral rights, which belong to the individual authors and are inalienable and cannot be waived (articles 19 and 21), from economic rights, which the owner may license (article 30). The MIT License is a non-exclusive license of the economic rights: it does not assign them and does not affect moral rights. Ownership remains with Transgenia.org and with the relevant third-party authors.
- Transgenia.org may register the Software with the National Copyright Institute (INDAUTOR). Such registration does not alter the MIT License or the rights it grants to the User and to any third party. Infringement claims in Mexico are handled under the LFDA.

### 7.2 Claims under United States law (DMCA)

- To the extent applicable, where anyone claims that the Software, the repository or the documentation infringes copyright under United States law, or where the material is hosted on a platform subject to that law (such as GitHub), the procedure of the Digital Millennium Copyright Act (DMCA) shall be followed. Notices may be sent to notificaciones@transgenia.org or filed through GitHub's procedure.
- While a claim is being resolved, Transgenia.org may remove or disable the allegedly infringing material in its repositories and channels, and shall handle counter-notices filed under the DMCA.

---

## 8. SUPPORT AND PROFESSIONAL SERVICES

### 8.1 Free, best-effort support

- Transgenia.org may respond to questions, bug reports and feature requests through the public repository's issues, as its capacity allows. That support includes no service levels, no response times and no obligation to fix, update or maintain the Software.
- Transgenia.org may modify, stop maintaining or withdraw the Software or the Services at any time. Copies of the Software that the User has already obtained keep the MIT License.

### 8.2 Paid services

- Maintenance, support with service levels, training, custom development, Odoo migrations, assisted deployment and the premium edition are contracted with Transgenia.org through its official channels and are governed by the Commercial Master Agreement and its annexes, not by these Terms.

### 8.3 Official channels

- Transgenia.org's only official channels for the Software are those listed in section 14. Any communication from other channels that offers support on Transgenia.org's behalf, or that asks for credentials, must be treated as unofficial.

### 8.4 Vulnerability reports

- Security vulnerabilities must be reported privately as described in the repository's `SECURITY.md` file, not through public issues.

---

## 9. ACCEPTABLE USE

- The rules in this section apply to the Services and restate obligations that the User already has under law or under agreements with third parties; they are not conditions of the MIT License (section 2.2). In their relationship with Transgenia.org and when using the Services, the User agrees not to:
  - use the Software to access Odoo instances or data that the User is not authorized to access;
  - use the Software to circumvent the Odoo Enterprise Edition license or the Odoo Online terms;
  - process personal data in breach of applicable law;
  - post credentials, personal data or confidential information in issues or public channels;
  - present a modified version of the Software as an official Transgenia.org product;
  - send spam or unlawful or abusive content through Transgenia.org's channels, or attack or overload its infrastructure.
- In response to conduct contrary to this section, Transgenia.org may moderate or close issues, block accounts in its repositories and channels, and stop assisting the User.
- The User is responsible for reviewing the actions their AI agent performs on their Odoo instance. Testing them in the local test environment or on a test database before working on production, and keeping backups, is recommended.

---

## 10. NO WARRANTY AND LIMITATION OF LIABILITY

### 10.1 No warranty

- In accordance with the MIT License and to the extent permitted by applicable law, the Software is provided “as is”, without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose and non-infringement. The free Services are provided on the same basis. This exclusion, which restates the text of the MIT License, is construed under Mexican law and does not affect the non-waivable rights referred to in section 12.1.
- Output produced by an AI agent with the Software is an aid. The User remains responsible for reviewing it before applying it in production.

### 10.2 Limitation of liability

- To the maximum extent permitted by applicable law, Transgenia.org shall not be liable for direct or indirect damages, loss of data, loss of profits or claims arising from the use of, or inability to use, the Software or the free Services, in accordance with the MIT License and these Terms.
- This limitation does not apply to liability for wilful misconduct or fraud (dolo) or bad faith, a waiver of which is void under article 2106 of the Federal Civil Code (Código Civil Federal), nor to liability for gross negligence, nor where applicable law prohibits excluding or limiting liability, and is without prejudice to the non-waivable rights of a User who qualifies as a consumer (section 12.1).

---

## 11. CHANGES TO THE TERMS

- Transgenia.org may update these Terms. Each version will be published in the Software's repository and at <https://transgenia.org>, with its version number and issue date.
- Changes take effect upon publication. Material changes will be announced in the repository's change log (`CHANGELOG`) and take effect 15 calendar days after publication.
- Continued use of the Services after a new version takes effect constitutes acceptance of it. No change to these Terms affects the MIT License of versions of the Software already distributed.
- Questions about changes to these Terms and to other legal and privacy documents may be sent to notificaciones@transgenia.org.

---

## 12. GOVERNING LAW, JURISDICTION AND PRECEDENCE OF RULES

### 12.1 Governing law and jurisdiction

- These Terms are governed by and construed in accordance with the federal laws of the United Mexican States, in particular the LFDA, the LFPPI, the LFPDPPP, the Federal Civil Code and, for commercial acts, the Code of Commerce (Código de Comercio). For any dispute arising from them, the parties submit to the competent courts of Mexico City and waive any other jurisdiction that may correspond to them by reason of their present or future domicile, except as provided in the next paragraph.
- Where the User qualifies as a consumer under article 2 of the Federal Consumer Protection Law (Ley Federal de Protección al Consumidor, LFPC), the User keeps the rights that law grants, which cannot be waived (article 1) and prevail over any provision of these Terms to the contrary, including the right to go to the Federal Consumer Protection Agency (PROFECO). The foregoing is also without prejudice to mandatory data protection or consumer protection rules that apply to the User in their place of residence.

### 12.2 Precedence and coordination of rules

- In case of conflict between the laws mentioned in these Terms (LFDA, LFPPI, LFPDPPP, LFPC, Federal Civil Code, Code of Commerce, GDPR, DMCA or others) and these Terms, the rules that are mandatory in the relevant jurisdiction shall apply, without rendering the rest of these Terms void. The foreign laws cited apply only to the extent applicable.
- If any provision of these Terms is void or unenforceable, the remaining provisions remain valid.
- Order of precedence: (i) as to the Software, the MIT License; (ii) as to contracted services, the Commercial Master Agreement and its annexes, where one exists; and (iii) in all other matters, these Terms.

### 12.3 Language

- The Spanish version of these Terms is the only legally binding version and prevails. This English version is a faithful translation, with the same structure and numbering, provided for convenience only; in case of discrepancy, the Spanish version prevails.

---

## 13. ACCEPTANCE

- By downloading, installing, accessing or using the Software or the Services, the User acknowledges having read, understood and accepted these Terms in everything that concerns their relationship with Transgenia.org.
- Acceptance by electronic means constitutes express consent under article 1803 of the Federal Civil Code and, for commercial acts, takes effect under articles 80 and 89 et seq. of the Code of Commerce.
- Acceptance of these Terms is not a condition for exercising the rights granted by the MIT License. If the User does not agree with them, the User may keep using the Software under the MIT License but must refrain from using the Services.

---

## 14. CONTACT AND OFFICIAL CHANNELS

- **Email (technical and commercial matters):** dev@transgenia.org
- **WhatsApp:** +52 55 8034 0405 (<https://wa.me/525580340405>)
- **Website:** <https://transgenia.org>
- **Legal and privacy notices (including ARCO, erasure and DMCA requests):** notificaciones@transgenia.org. Privacy Notice: <https://transgenia.org/legal-privacidad.html>
- **Bug reports and feature requests:** issues in the repository <https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online>
- **Security vulnerabilities:** as described in the repository's `SECURITY.md` file.

---

**Referenced annexes (non-exhaustive):**

- MIT License (the repository's `LICENSE` file).
- `NOTICE` file (third-party components and their licenses).
- Plugin privacy policy (`PRIVACY.md`) and security policy (`SECURITY.md`).
- Transgenia.org Privacy Notice (<https://transgenia.org/legal-privacidad.html>).
- Applicable third-party licenses: GNU LGPL v3 (Odoo Community Edition); Odoo Enterprise Edition License v1.0 (Odoo Enterprise Edition); Odoo S.A. terms of service and subscription (Odoo Online); PostgreSQL License (PostgreSQL); and MIT License (odoo-agent).

These Terms may be updated as described in section 11.

---
