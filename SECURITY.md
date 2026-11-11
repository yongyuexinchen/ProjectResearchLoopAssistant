# Security Policy

## Supported versions

Security fixes are applied to the `main` branch and the latest tagged release, if any.

## Reporting a vulnerability

Please do not open a public issue containing credentials, tokens, private repository contents, or exploitable details.

Use GitHub's private vulnerability reporting / Security Advisories for this repository. Include:

- affected version or commit;
- a minimal reproduction;
- impact and any known mitigation.

## Local secrets

- `.env` is local-only and ignored by Git.
- Use `.env.example` as the template; never put real keys in it.
- If a key was committed, rotate it immediately and remove it from Git history with `git filter-repo`; deleting the current file is not enough.
- The collected workspace under `workspace/projects/` and run logs under `.tmp/` are local runtime data and are ignored by Git.
