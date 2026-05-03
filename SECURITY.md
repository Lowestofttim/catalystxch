# CATalyst Website Security Policy

This repository serves the static public website for CATalyst through GitHub Pages.

## Current Site Rules

- The site is static HTML/CSS/JS only. It does not accept form input, store user data, or run a backend service.
- Pages must use HTTPS-only asset links. Avoid plain-HTTP URLs.
- Avoid third-party scripts, analytics, widgets, remote fonts, and embeds.
- External links must use `rel="noopener"` when opened in a new tab.
- Keep the Content Security Policy in `index.html` and `docs.html` aligned with the smallest needed permissions.

## Download Rules

When public downloads are enabled:

- Link only to official GitHub Releases for the main CATalyst app repository.
- Show the release version, release notes, file size, and SHA-256 checksum next to each download.
- Do not use mirrors, URL shorteners, chat-only installer links, or files uploaded directly into this website repository.
- Keep release asset names predictable, for example `Catalyst-Setup-vX.Y.Z.exe`.
- CATalyst must never ask users for a seed phrase or private keys. Sage signs locally.

## Reporting

While the app repository is private, report website or download safety issues through the early-tester support channel. When the main CATalyst app repository becomes public, use its public issue tracker for coordinated reports.
