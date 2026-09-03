(() => {
  const METADATA_URL = "assets/release/latest.json";
  const MAC_SOURCE_URL = "https://github.com/catalystxch/catalyst-bot";

  const setText = (selector, value) => {
    if (value === undefined || value === null) return;
    document.querySelectorAll(selector).forEach((node) => {
      node.textContent = value;
    });
  };

  const setHidden = (selector, hidden) => {
    document.querySelectorAll(selector).forEach((node) => {
      node.hidden = hidden;
    });
  };

  const formatDate = (value) => {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric"
    });
  };

  const formatBytes = (value) => {
    if (!Number.isFinite(value) || value <= 0) return "";
    const units = ["B", "KB", "MB", "GB"];
    let size = value;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
      size /= 1024;
      unit += 1;
    }
    return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
  };

  const isAllowedDownloadUrl = (value, platform) => {
    if (typeof value !== "string") return false;
    if (platform === "windows") {
      return value.startsWith("https://github.com/Lowestofttim/catalyst-releases/releases/download/");
    }
    if (platform === "linux") {
      return value.startsWith("https://github.com/catalystxch/catalyst-bot/releases/download/");
    }
    return false;
  };

  const platformDownloadPriority = (asset, platform) => {
    const name = String(asset && asset.name || "").toLowerCase();
    if (platform === "linux") {
      if (name.endsWith(".deb")) return 0;
      if (name.endsWith(".appimage")) return 1;
    }
    return 50;
  };

  const isVerifiedWindowsInstaller = (asset) => {
    if (!asset || asset.download_enabled !== true || !asset.verification) return false;
    const nameMatch = /^Catalyst-Setup-(v\d+\.\d+\.\d+)\.exe$/.exec(asset.name || "");
    if (!nameMatch) return false;
    const tag = nameMatch[1];
    const releaseBase = `https://github.com/Lowestofttim/catalyst-releases/releases/download/${tag}/`;
    return (
      asset.download_url === `${releaseBase}${asset.name}` &&
      /^[a-f0-9]{64}$/.test(asset.sha256 || "") &&
      asset.distribution_status !== "unsigned_beta" &&
      asset.verification.authenticode_status === "valid" &&
      asset.verification.publisher === "SignPath Foundation" &&
      asset.verification.timestamp_status === "valid" &&
      asset.verification.update_manifest_status === "valid" &&
      asset.verification.update_manifest_url === `${releaseBase}latest.json` &&
      asset.verification.update_manifest_signature_url === `${releaseBase}latest.json.sig` &&
      asset.verification.evidence_url === `${releaseBase}windows-signature-${tag}.json` &&
      /^[A-F0-9]{40}$/.test(asset.verification.signer_thumbprint || "") &&
      /^[a-f0-9]{64}$/.test(asset.verification.evidence_sha256 || "")
    );
  };

  const isUnsignedWindowsBeta = (asset) => {
    if (!asset || asset.download_enabled !== true || !asset.verification) return false;
    const nameMatch = /^Catalyst-Setup-(v\d+\.\d+\.\d+)\.exe$/.exec(asset.name || "");
    if (!nameMatch) return false;
    const releaseBase = `https://github.com/Lowestofttim/catalyst-releases/releases/download/${nameMatch[1]}/`;
    return (
      asset.distribution_status === "unsigned_beta" &&
      asset.download_url === `${releaseBase}${asset.name}` &&
      /^[a-f0-9]{64}$/.test(asset.sha256 || "") &&
      asset.verification.authenticode_status === "unsigned" &&
      asset.verification.publisher === null &&
      asset.verification.signer_subject === null &&
      asset.verification.signer_thumbprint === null &&
      asset.verification.timestamp_status === "unavailable" &&
      asset.verification.update_manifest_status === "valid" &&
      asset.verification.update_manifest_url === `${releaseBase}latest.json` &&
      asset.verification.update_manifest_signature_url === `${releaseBase}latest.json.sig` &&
      asset.verification.evidence_url === null &&
      asset.verification.evidence_sha256 === null
    );
  };

  const findAsset = (latest, platform, kind) => {
    if (!Array.isArray(latest.assets)) return null;
    const candidates = latest.assets.filter((asset) => (
      asset &&
      asset.platform === platform &&
      asset.kind === kind &&
      asset.download_enabled === true &&
      isAllowedDownloadUrl(asset.download_url, platform) &&
      typeof asset.sha256 === "string"
    ));
    candidates.sort((a, b) => (
      platformDownloadPriority(a, platform) - platformDownloadPriority(b, platform) ||
      String(a.name || "").localeCompare(String(b.name || ""))
    ));
    return candidates[0] || null;
  };

  const findWindowsInstaller = (latest) => {
    const asset = findAsset(latest, "windows", "installer");
    return (isVerifiedWindowsInstaller(asset) || isUnsignedWindowsBeta(asset)) ? asset : null;
  };
  const findPlatformDownload = (latest, platform) => (
    findAsset(latest, platform, "installer") ||
    findAsset(latest, platform, "archive")
  );

  const renderList = (selector, items) => {
    if (!Array.isArray(items) || !items.length) return;
    document.querySelectorAll(selector).forEach((list) => {
      list.textContent = "";
      items.forEach((item) => {
        if (typeof item !== "string" || !item.trim()) return;
        const li = document.createElement("li");
        li.textContent = item.trim();
        list.appendChild(li);
      });
    });
  };

  const disableDownload = (selector) => {
    document.querySelectorAll(selector).forEach((link) => {
      link.removeAttribute("href");
      link.removeAttribute("target");
      link.removeAttribute("rel");
      link.setAttribute("aria-disabled", "true");
      link.setAttribute("tabindex", "-1");
      link.classList.add("is-disabled");
    });
  };

  const enableDownload = (selector, asset) => {
    document.querySelectorAll(selector).forEach((link) => {
      link.setAttribute("href", asset.download_url);
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noopener");
      link.removeAttribute("aria-disabled");
      link.removeAttribute("tabindex");
      link.classList.remove("is-disabled");
    });
  };

  const enableMacSourceLink = () => {
    setText("[data-release-macos-size]", "GitHub source");
    setText("[data-release-macos-sha256]", "Source only from GitHub");
    document.querySelectorAll("[data-download-macos]").forEach((link) => {
      link.setAttribute("href", MAC_SOURCE_URL);
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noopener");
      link.removeAttribute("aria-disabled");
      link.removeAttribute("tabindex");
      link.classList.remove("is-disabled");
    });
  };

  const disableWindowsDownload = () => {
    setHidden("[data-windows-download-notice]", false);
    setText("[data-windows-download-notice-title]", "Windows download temporarily unavailable");
    setText(
      "[data-windows-download-notice-body]",
      "CATalyst v1.3.17 is temporarily withheld because Microsoft Defender currently classifies its installer as Trojan:Win32/Wacatac.B!ml. Do not bypass this alert. Linux packages and the source code remain available while a replacement Windows build is verified."
    );
    setText("[data-release-download-name]", "Not available");
    setText("[data-release-download-size]", "");
    setText("[data-release-sha256]", "Not available");
    setText(
      "[data-release-windows-signature]",
      "Windows installer unavailable - signature verification required"
    );
    setText("[data-release-windows-tag]", "Unavailable");
    disableDownload("[data-download-windows]");
  };

  const applyMetadata = (metadata) => {
    const latest = metadata && metadata.latest;
    if (!latest || typeof latest.version !== "string") return;

    const version = latest.version;
    const releaseDate = formatDate(latest.published_at);
    const windowsInstaller = findWindowsInstaller(latest);
    const linuxDownload = findPlatformDownload(latest, "linux");
    const downloadsAvailable = Boolean(windowsInstaller);
    const status = downloadsAvailable
      ? (linuxDownload ? "Windows/Linux downloads available" : "Windows download available")
      : (linuxDownload ? "Linux download available" : "Public links coming soon");
    const channel = latest.channel === "prerelease" ? "Prerelease" : "Stable";
    const meta = releaseDate
      ? `${channel} - published ${releaseDate} - ${status.toLowerCase()}`
      : `${channel} - ${status.toLowerCase()}`;

    setText("[data-release-version]", version);
    setText("[data-release-name]", latest.name || version);
    setText("[data-release-status]", status);
    setText("[data-release-meta]", meta);
    setText(
      "[data-release-eyebrow]",
      (downloadsAvailable || linuxDownload)
        ? `${status} - current release ${version}`
        : `Public downloads coming soon - current beta ${version}`
    );
    setText("[data-release-date]", releaseDate ? `Released ${releaseDate}` : "");
    renderList("[data-release-notes]", latest.release_notes);
    enableMacSourceLink();

    setText("[data-release-linux-size]", linuxDownload ? formatBytes(linuxDownload.size_bytes) : "");
    setText("[data-release-linux-sha256]", linuxDownload ? linuxDownload.sha256 : "Not available");
    if (linuxDownload) enableDownload("[data-download-linux]", linuxDownload);
    else disableDownload("[data-download-linux]");

    if (!downloadsAvailable) {
      disableWindowsDownload();
      return;
    }

    const size = formatBytes(windowsInstaller.size_bytes);
    const unsignedWindowsBeta = isUnsignedWindowsBeta(windowsInstaller);
    setText("[data-release-download-name]", windowsInstaller.name);
    setText("[data-release-download-size]", size);
    setText("[data-release-sha256]", windowsInstaller.sha256);
    setText(
      "[data-release-windows-signature]",
      unsignedWindowsBeta
        ? "Unsigned beta - expect a Windows SmartScreen warning"
        : "Verified publisher: SignPath Foundation"
    );
    setText(
      "[data-release-windows-tag]",
      unsignedWindowsBeta ? "Unsigned beta" : "Verified"
    );
    if (unsignedWindowsBeta) {
      setText("[data-windows-download-notice-title]", "Unsigned Windows beta");
      setText(
        "[data-windows-download-notice-body]",
        "Windows may show a blue 'Windows protected your PC' warning because this beta installer is not digitally signed. Download only from this page, verify the SHA-256 checksum shown below, then use More info -> Run anyway if you choose to proceed. Do not continue if Windows reports malware or potentially unwanted software rather than the blue unrecognized-app warning."
      );
    }
    setHidden("[data-windows-download-notice]", !unsignedWindowsBeta);
    enableDownload("[data-download-windows]", windowsInstaller);
  };

  const loadMetadata = async () => {
    try {
      const response = await fetch(METADATA_URL, { cache: "no-store" });
      if (!response.ok) return;
      applyMetadata(await response.json());
    } catch (_) {
      // Keep the static fallback text if the metadata file cannot be loaded.
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadMetadata, { once: true });
  } else {
    loadMetadata();
  }
  if (typeof window !== "undefined" && window.addEventListener) {
    window.addEventListener("pageshow", (event) => {
      if (event && event.persisted) loadMetadata();
    });
  }
  if (document.addEventListener) {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") loadMetadata();
    });
  }
})();
