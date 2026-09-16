# Security Policy

## Supported versions

This is a young project with a single active line. Security fixes land on the
latest release; there is no long-term support branch.

| Version | Supported |
| --- | --- |
| latest release | yes |
| anything older | no — please update first |

## Reporting a vulnerability

Please report privately rather than in a public issue:

**[Open a private security advisory](https://github.com/yakupafsin/fuse-energy-ha/security/advisories/new)**

That goes only to the maintainer. Expect an acknowledgement within a week.

If you would rather not use GitHub's advisory flow, open a public issue saying
only that you have found a security problem and would like a private channel —
with no details — and one will be arranged.

## What is worth reporting

This integration holds credentials that can access a live energy account, so
the things that matter most are:

- **Credential exposure** — a token, refresh token, `device_id` or phone number
  appearing in logs, diagnostics, traces, or an error message.
- **Anything that weakens the auth flow**, or makes the integration accept a
  response it should not.
- **Dependency issues** — though note the integration has no third-party
  requirements; it uses only what Home Assistant already ships.

## What is not a vulnerability

- **That the API is private and undocumented.** This is stated plainly in the
  README. It is a stability and terms-of-service consideration, not a security
  flaw.
- **Tokens stored in `.storage`.** That is where Home Assistant keeps config
  entry data for every integration, protected by the host's filesystem
  permissions. If you can read `.storage`, the HA instance is already yours.

## Handling of credentials

For reference when assessing a report, the integration:

- stores its tokens in the Home Assistant config entry, never on disk itself;
- **excludes tokens and the phone number from diagnostics** by building the
  diagnostics payload from an explicit allow-list, rather than redacting a dump
  — so a newly added field cannot leak by being forgotten;
- has no third-party runtime dependencies.
