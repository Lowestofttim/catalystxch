# CATalyst website and beta feedback

This is the public website repository for CATalyst:

- Website: https://catalystxch.com
- Docs: https://catalystxch.com/docs.html
- Downloads: https://catalystxch.com/#download

This repository is intentionally separate from the main CATalyst bot source code. It gives testers a public place to read the website and download the current public installer while the app source, bug reports, and beta feedback live in the public bot repository.

## What this repository contains

- The static CATalyst website and help docs.
- Public release metadata used by the website download panel.
- Redirect links for beta bug reports and feedback.
- Security rules for the website and public download links.

The website is static HTML, CSS, JavaScript, and image assets. It does not run a backend service, store visitor data, or process wallet information.

## What this repository is not

This is not the main CATalyst trading bot source repository.

Please do not expect the full app code, trading engine, wallet adapters, build scripts, or development history to live in this website repository. Those belong in the separate CATalyst app source repository.

## Download CATalyst

Use the download section on the website:

https://catalystxch.com/#download

Current public Windows installers are hosted through the official CATalyst public release channel:

https://github.com/Lowestofttim/catalyst-releases/releases

The website shows the current version, release notes, file size, and SHA-256 checksum next to the download buttons. Windows uses the signed public installer channel, while macOS and Linux downloads point at the official bot release assets. Avoid installer links sent only by chat, URL shorteners, mirrors, or files uploaded directly to this website repository.

## Report a bug

Use the public bug report form:

https://github.com/catalystxch/catalyst-bot/issues/new?template=bug_report.yml

Bug reports are useful for:

- Installer or update problems.
- First launch and setup issues.
- Sage wallet connection problems.
- App crashes or confusing behavior.
- Website or docs mistakes.

If the app still opens, go to the Logs tab and click **Debug Bundle**. You can attach the downloaded `bot_debug_bundle_...zip` to the bug report if it is under GitHub's file upload limit.

Debug Bundles are redacted by default. Wallet addresses, Sage fingerprints, RPC/TLS paths, API tokens, cookies, passwords, seed/private-key labels, and local user-folder paths are redacted from bundled log tails and snapshots. `.env`, database files, wallet secret files, and wallet key material are not included.

GitHub issues are public. Please review anything you attach before submitting it.

## Send feedback

Use the public feedback form:

https://github.com/catalystxch/catalyst-bot/issues/new?template=feedback.yml

Feedback is useful for:

- Setup steps that were confusing.
- App wording that was unclear.
- Missing help page content.
- Feature ideas.
- Workflow improvements for non-technical users.

## Do not post secrets

Do not include seed phrases, private keys, wallet backups, API keys, passwords, `.env` files, database files, or anything you would not want public.

CATalyst should never ask for your seed phrase or private keys. Sage signs locally on your machine.

## Website changes

Small website, docs, and README fixes can be proposed in this repository. Changes should keep the site static, avoid unnecessary third-party scripts, and keep download links pointed only at official CATalyst GitHub Releases.

Developers who want to improve the bot itself should use the public bot repository:

https://github.com/catalystxch/catalyst-bot

Release metadata is stored in `assets/release/latest.json`. Maintainers can validate release wiring with:

```bash
python scripts/check_release_metadata.py
python scripts/check_sync_release_fallbacks.py
python scripts/check_sync_workflow.py
node scripts/check_release_js_behavior.js
python scripts/check_release_dom_rendering.py
npx --yes html-validate index.html docs.html
```

The hourly and manually dispatchable `Sync release metadata` workflow reads the
latest Windows release from `Lowestofttim/catalyst-releases`, reads the matching
Linux packages from `catalystxch/catalyst-bot`, updates the JSON and static HTML
fallbacks, runs the checks above, and uses a short-lived pull request to update
protected `main` only when the public release changes. It then explicitly starts a
GitHub Pages build so automation-authored commits are published immediately.
The repository setting that permits GitHub Actions to create pull requests must
remain enabled; the workflow does not approve reviews or bypass branch protection.
