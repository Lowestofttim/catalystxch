#!/usr/bin/env node
"use strict";

const fs = require("fs");
const vm = require("vm");

const RELEASE_JS = "assets/release.js";
const MAC_SOURCE_URL = "https://github.com/catalystxch/catalyst-bot";
const metadata = JSON.parse(fs.readFileSync("assets/release/latest.json", "utf8"));
const baseLatest = metadata.latest;
const windowsInstaller = baseLatest.assets.find((asset) => asset.platform === "windows" && asset.kind === "installer");
const verifiedWindows = {
  ...windowsInstaller,
  download_url: `https://github.com/Lowestofttim/catalyst-releases/releases/download/${baseLatest.version}/${windowsInstaller.name}`,
  sha256: "a".repeat(64),
  download_enabled: true,
  verification: {
    authenticode_status: "valid",
    publisher: "SignPath Foundation",
    signer_subject: "CN=SignPath Foundation, O=SignPath Foundation",
    signer_thumbprint: "A".repeat(40),
    timestamp_status: "valid",
    update_manifest_status: "valid",
    update_manifest_url: `https://github.com/Lowestofttim/catalyst-releases/releases/download/${baseLatest.version}/latest.json`,
    update_manifest_signature_url: `https://github.com/Lowestofttim/catalyst-releases/releases/download/${baseLatest.version}/latest.json.sig`,
    evidence_url: `https://github.com/Lowestofttim/catalyst-releases/releases/download/${baseLatest.version}/windows-signature-${baseLatest.version}.json`,
    evidence_sha256: "c".repeat(64)
  }
};
const verifiedLatest = {
  ...baseLatest,
  assets: baseLatest.assets.map((asset) => asset === windowsInstaller ? verifiedWindows : asset)
};
const platformDownloadPriority = (asset, platform) => {
  const name = String(asset && asset.name || "").toLowerCase();
  if (platform === "linux") {
    if (name.endsWith(".deb")) return 0;
    if (name.endsWith(".appimage")) return 1;
  }
  return 50;
};
const findPlatformDownload = (platform) => (
  [...baseLatest.assets]
    .filter((asset) => asset.platform === platform && asset.kind === "installer")
    .sort((a, b) => (
      platformDownloadPriority(a, platform) - platformDownloadPriority(b, platform) ||
      String(a.name || "").localeCompare(String(b.name || ""))
    ))[0] ||
  [...baseLatest.assets]
    .filter((asset) => asset.platform === platform && asset.kind === "archive")
    .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")))[0]
);
const linuxDownload = findPlatformDownload("linux");
const macosDownload = baseLatest.assets.find((asset) => asset.platform === "macos");

function formatBytes(value) {
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

if (!windowsInstaller) {
  throw new Error("latest.json must contain a Windows installer asset");
}
if (macosDownload) {
  throw new Error("latest.json must not contain macOS package download assets");
}
if (!linuxDownload) {
  throw new Error("latest.json must contain a Linux download asset");
}
if (!linuxDownload.name.toLowerCase().endsWith(".deb")) {
  throw new Error("Linux website download should prefer the .deb package");
}

const PUBLIC_URL = verifiedWindows.download_url;
const SHA256 = verifiedWindows.sha256;
const DOWNLOAD_NAME = windowsInstaller.name;
const DOWNLOAD_SIZE = formatBytes(windowsInstaller.size_bytes);
const LINUX_URL = linuxDownload.download_url;

function makeTextNode(textContent = "") {
  return { textContent };
}

function makeListNode() {
  return {
    textContent: "",
    items: [],
    appendChild(node) {
      this.items.push(node.textContent);
    }
  };
}

function makeLinkNode(initialHref = "") {
  const attrs = new Map([
    ["aria-disabled", "true"],
    ["tabindex", "-1"]
  ]);
  if (initialHref) attrs.set("href", initialHref);

  return {
    href: initialHref,
    attrs,
    classList: {
      values: new Set(["is-disabled"]),
      add(name) {
        this.values.add(name);
      },
      remove(name) {
        this.values.delete(name);
      },
      contains(name) {
        return this.values.has(name);
      }
    },
    setAttribute(name, value) {
      this.attrs.set(name, value);
      if (name === "href") this.href = value;
    },
    removeAttribute(name) {
      this.attrs.delete(name);
      if (name === "href") this.href = "";
    },
    getAttribute(name) {
      return this.attrs.get(name) || null;
    }
  };
}

function buildDocument(link, macosLink, linuxLink) {
  const nodes = new Map([
    ["[data-release-version]", [makeTextNode()]],
    ["[data-release-name]", [makeTextNode()]],
    ["[data-release-status]", [makeTextNode()]],
    ["[data-release-meta]", [makeTextNode()]],
    ["[data-release-eyebrow]", [makeTextNode()]],
    ["[data-release-date]", [makeTextNode()]],
    ["[data-release-download-name]", [makeTextNode(DOWNLOAD_NAME)]],
    ["[data-release-download-size]", [makeTextNode(DOWNLOAD_SIZE)]],
    ["[data-release-macos-size]", [makeTextNode("GitHub source")]],
    ["[data-release-linux-size]", [makeTextNode(formatBytes(linuxDownload.size_bytes))]],
    ["[data-release-sha256]", [makeTextNode(SHA256)]],
    ["[data-release-windows-signature]", [makeTextNode()]],
    ["[data-release-macos-sha256]", [makeTextNode("Source only from GitHub")]],
    ["[data-release-linux-sha256]", [makeTextNode(linuxDownload.sha256)]],
    ["[data-release-notes]", [makeListNode()]],
    ["[data-download-windows]", [link]],
    ["[data-download-macos]", [macosLink]],
    ["[data-download-linux]", [linuxLink]]
  ]);

  return {
    nodes,
    document: {
      readyState: "complete",
      querySelectorAll(selector) {
        return nodes.get(selector) || [];
      },
      createElement(tag) {
        return { tag, textContent: "" };
      },
      addEventListener() {
        throw new Error("unexpected DOMContentLoaded listener");
      }
    }
  };
}

async function runRelease(metadata, initialHref = "") {
  return runReleaseSequence([metadata], initialHref);
}

async function runReleaseSequence(metadataResponses, initialHref = "") {
  const code = fs.readFileSync(RELEASE_JS, "utf8");
  const link = makeLinkNode(initialHref);
  const macosLink = makeLinkNode(initialHref);
  const linuxLink = makeLinkNode(initialHref);
  const { document, nodes } = buildDocument(link, macosLink, linuxLink);
  const windowEventHandlers = new Map();
  const documentEventHandlers = new Map();
  let fetchCount = 0;
  document.visibilityState = "visible";
  document.addEventListener = (name, handler) => {
    documentEventHandlers.set(name, handler);
  };
  const context = {
    console,
    document,
    window: {
      addEventListener(name, handler) {
        windowEventHandlers.set(name, handler);
      }
    },
    fetch: async (url) => ({
      ok: url === "assets/release/latest.json",
      json: async () => {
        const index = Math.min(fetchCount, metadataResponses.length - 1);
        fetchCount += 1;
        return metadataResponses[index];
      }
    })
  };

  vm.runInNewContext(code, context, { filename: RELEASE_JS });
  await new Promise((resolve) => setImmediate(resolve));

  return {
    link,
    macosLink,
    linuxLink,
    nodes,
    async dispatchWindowEvent(name, event = {}) {
      const handler = windowEventHandlers.get(name);
      if (!handler) throw new Error(`${name} handler should be registered`);
      handler(event);
      await new Promise((resolve) => setImmediate(resolve));
    },
    async dispatchDocumentEvent(name, event = {}) {
      const handler = documentEventHandlers.get(name);
      if (!handler) throw new Error(`${name} handler should be registered`);
      handler(event);
      await new Promise((resolve) => setImmediate(resolve));
    },
    setVisibilityState(value) {
      document.visibilityState = value;
    },
    get fetchCount() {
      return fetchCount;
    },
    text(selector) {
      return nodes.get(selector)[0].textContent;
    }
  };
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function main() {
  const enabled = await runRelease({ downloads_enabled: true, latest: verifiedLatest });
  assert(enabled.link.href === PUBLIC_URL, "enabled release should set the Windows download href");
  assert(enabled.macosLink.href === MAC_SOURCE_URL, "enabled release should keep macOS on the source repo href");
  assert(enabled.linuxLink.href === LINUX_URL, "enabled release should set the Linux download href");
  assert(enabled.link.attrs.get("target") === "_blank", "enabled release should set target");
  assert(enabled.link.attrs.get("rel") === "noopener", "enabled release should set rel");
  assert(!enabled.link.attrs.has("aria-disabled"), "enabled release should remove aria-disabled");
  assert(!enabled.macosLink.attrs.has("aria-disabled"), "macOS source link should remain enabled");
  assert(!enabled.link.classList.contains("is-disabled"), "enabled release should remove is-disabled");
  assert(enabled.text("[data-release-name]") === baseLatest.name, "enabled release should show the release name");
  assert(enabled.text("[data-release-version]") === baseLatest.version, "enabled release should show the release version");
  assert(enabled.text("[data-release-sha256]") === SHA256, "enabled release should show SHA-256");
  assert(enabled.text("[data-release-windows-signature]") === "Verified publisher: SignPath Foundation", "enabled release should show verified publisher");
  assert(enabled.text("[data-release-macos-size]") === "GitHub source", "enabled release should show macOS source status");
  assert(enabled.text("[data-release-linux-size]") === formatBytes(linuxDownload.size_bytes), "enabled release should show Linux size");
  assert(enabled.text("[data-release-macos-sha256]") === "Source only from GitHub", "enabled release should show macOS source-only detail");
  assert(enabled.text("[data-release-linux-sha256]") === linuxDownload.sha256, "enabled release should show Linux SHA-256");

  const disabled = await runRelease(metadata, PUBLIC_URL);
  assert(disabled.link.href === "", "disabled release should remove stale Windows download href");
  assert(disabled.macosLink.href === MAC_SOURCE_URL, "disabled release should preserve macOS source href");
  assert(disabled.linuxLink.href === LINUX_URL, "disabled Windows should preserve Linux download href");
  assert(!disabled.link.attrs.has("target"), "disabled release should remove target");
  assert(!disabled.link.attrs.has("rel"), "disabled release should remove rel");
  assert(disabled.link.attrs.get("aria-disabled") === "true", "disabled release should mark the link disabled");
  assert(!disabled.macosLink.attrs.has("aria-disabled"), "disabled release should leave macOS source link enabled");
  assert(disabled.link.classList.contains("is-disabled"), "disabled release should add is-disabled");
  assert(disabled.text("[data-release-download-name]") === "Not available", "disabled release should reset installer detail");
  assert(disabled.text("[data-release-download-size]") === "", "disabled release should reset file size");
  assert(disabled.text("[data-release-sha256]") === "Not available", "disabled release should reset SHA-256 detail");
  assert(disabled.text("[data-release-windows-signature]") === "Windows installer unavailable - signature verification required", "disabled release should show signature requirement");
  assert(disabled.text("[data-release-macos-sha256]") === "Source only from GitHub", "disabled release should keep macOS source-only detail");
  assert(disabled.text("[data-release-linux-sha256]") === linuxDownload.sha256, "disabled Windows should preserve Linux SHA-256 detail");

  const guardedCases = [
    {
      name: "URL and hash only",
      asset: { ...verifiedWindows, verification: undefined }
    },
    {
      name: "wrong publisher",
      asset: { ...verifiedWindows, verification: { ...verifiedWindows.verification, publisher: "Unknown" } }
    },
    {
      name: "missing timestamp",
      asset: { ...verifiedWindows, verification: { ...verifiedWindows.verification, timestamp_status: "unavailable" } }
    },
    {
      name: "missing CATalyst manifest signature",
      asset: { ...verifiedWindows, verification: { ...verifiedWindows.verification, update_manifest_status: "unavailable" } }
    },
    {
      name: "untrusted manifest URL",
      asset: { ...verifiedWindows, verification: { ...verifiedWindows.verification, update_manifest_url: "https://example.com/latest.json" } }
    },
    {
      name: "wrong host",
      asset: { ...verifiedWindows, download_url: `https://example.com/${DOWNLOAD_NAME}` }
    }
  ];
  for (const testCase of guardedCases) {
    const guardedLatest = {
      ...baseLatest,
      assets: baseLatest.assets.map((asset) => asset === windowsInstaller ? testCase.asset : asset)
    };
    const guardFailure = await runRelease({ downloads_enabled: true, latest: guardedLatest }, PUBLIC_URL);
    assert(guardFailure.link.href === "", `${testCase.name} should remove stale Windows href`);
    assert(guardFailure.link.attrs.get("aria-disabled") === "true", `${testCase.name} should mark Windows disabled`);
    assert(guardFailure.linuxLink.href === LINUX_URL, `${testCase.name} should preserve Linux`);
  }

  const staleLatest = {
    version: "v1.2.6",
    name: "CATalyst v1.2.6",
    published_at: "2026-01-01T00:00:00Z",
    channel: "stable",
    release_notes: ["Old cached release fallback"],
    assets: []
  };
  const restored = await runReleaseSequence([
    { downloads_enabled: false, latest: staleLatest },
    { downloads_enabled: true, latest: verifiedLatest }
  ]);
  assert(restored.text("[data-release-version]") === "v1.2.6", "stale restored page should start on the old version");
  await restored.dispatchWindowEvent("pageshow", { persisted: true });
  assert(restored.fetchCount === 2, "pageshow restore should refetch release metadata");
  assert(restored.text("[data-release-version]") === baseLatest.version, "pageshow restore should replace the stale version");
  assert(restored.link.href === PUBLIC_URL, "pageshow restore should re-enable the current Windows download");

  const visibleAgain = await runReleaseSequence([
    { downloads_enabled: false, latest: staleLatest },
    { downloads_enabled: true, latest: verifiedLatest }
  ]);
  assert(visibleAgain.text("[data-release-version]") === "v1.2.6", "backgrounded page should start on the old version");
  visibleAgain.setVisibilityState("visible");
  await visibleAgain.dispatchDocumentEvent("visibilitychange");
  assert(visibleAgain.fetchCount === 2, "visible tab should refetch release metadata");
  assert(visibleAgain.text("[data-release-version]") === baseLatest.version, "visible tab should replace the stale version");

  console.log("release.js behavior check passed");
}

main().catch((error) => {
  console.error(`release.js behavior check failed: ${error.message}`);
  process.exit(1);
});
