(() => {
  const METADATA_URL = "assets/release/latest.json";

  const setText = (selector, value) => {
    if (value === undefined || value === null) return;
    document.querySelectorAll(selector).forEach((node) => {
      node.textContent = value;
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
    if (platform === "macos" || platform === "linux") {
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
    if (platform === "macos" && name.endsWith(".dmg")) return 0;
    return 50;
  };

  const findAsset = (latest, platform, kind) => {
    if (!Array.isArray(latest.assets)) return null;
    const candidates = latest.assets.filter((asset) => (
      asset &&
      asset.platform === platform &&
      asset.kind === kind &&
      isAllowedDownloadUrl(asset.download_url, platform) &&
      typeof asset.sha256 === "string"
    ));
    candidates.sort((a, b) => (
      platformDownloadPriority(a, platform) - platformDownloadPriority(b, platform) ||
      String(a.name || "").localeCompare(String(b.name || ""))
    ));
    return candidates[0] || null;
  };

  const findWindowsInstaller = (latest) => findAsset(latest, "windows", "installer");
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

  const disableWindowsDownload = () => {
    setText("[data-release-download-name]", "Not available");
    setText("[data-release-download-size]", "");
    setText("[data-release-sha256]", "Not available");
    setText("[data-release-macos-size]", "");
    setText("[data-release-linux-size]", "");
    setText("[data-release-macos-sha256]", "Not available");
    setText("[data-release-linux-sha256]", "Not available");
    disableDownload("[data-download-windows]");
  };

  const applyMetadata = (metadata) => {
    const latest = metadata && metadata.latest;
    if (!latest || typeof latest.version !== "string") return;

    const version = latest.version;
    const releaseDate = formatDate(latest.published_at);
    const windowsInstaller = metadata.downloads_enabled ? findWindowsInstaller(latest) : null;
    const macosDownload = metadata.downloads_enabled ? findPlatformDownload(latest, "macos") : null;
    const linuxDownload = metadata.downloads_enabled ? findPlatformDownload(latest, "linux") : null;
    const downloadsAvailable = Boolean(windowsInstaller);
    const status = downloadsAvailable ? "Windows download available" : "Public links coming soon";
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
      downloadsAvailable ? `Windows download available - current release ${version}` : `Public downloads coming soon - current beta ${version}`
    );
    setText("[data-release-date]", releaseDate ? `Released ${releaseDate}` : "");
    renderList("[data-release-notes]", latest.release_notes);

    if (!downloadsAvailable) {
      disableWindowsDownload();
      disableDownload("[data-download-macos]");
      disableDownload("[data-download-linux]");
      return;
    }

    const size = formatBytes(windowsInstaller.size_bytes);
    setText("[data-release-download-name]", windowsInstaller.name);
    setText("[data-release-download-size]", size);
    setText("[data-release-sha256]", windowsInstaller.sha256);
    setText("[data-release-macos-size]", macosDownload ? formatBytes(macosDownload.size_bytes) : "");
    setText("[data-release-linux-size]", linuxDownload ? formatBytes(linuxDownload.size_bytes) : "");
    setText("[data-release-macos-sha256]", macosDownload ? macosDownload.sha256 : "Not available");
    setText("[data-release-linux-sha256]", linuxDownload ? linuxDownload.sha256 : "Not available");

    enableDownload("[data-download-windows]", windowsInstaller);
    if (macosDownload) enableDownload("[data-download-macos]", macosDownload);
    else disableDownload("[data-download-macos]");
    if (linuxDownload) enableDownload("[data-download-linux]", linuxDownload);
    else disableDownload("[data-download-linux]");
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
})();
