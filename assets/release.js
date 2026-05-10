(() => {
  const METADATA_URL = "assets/release/latest.json";

  const setText = (selector, value) => {
    if (!value) return;
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

  const isAllowedDownloadUrl = (value) => {
    if (typeof value !== "string") return false;
    return value.startsWith("https://github.com/Lowestofttim/catalyst-releases/releases/download/");
  };

  const findWindowsInstaller = (latest) => {
    if (!Array.isArray(latest.assets)) return null;
    return latest.assets.find((asset) => (
      asset &&
      asset.platform === "windows" &&
      asset.kind === "installer" &&
      isAllowedDownloadUrl(asset.download_url) &&
      typeof asset.sha256 === "string"
    )) || null;
  };

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

  const applyMetadata = (metadata) => {
    const latest = metadata && metadata.latest;
    if (!latest || typeof latest.version !== "string") return;

    const version = latest.version;
    const releaseDate = formatDate(latest.published_at);
    const windowsInstaller = metadata.downloads_enabled ? findWindowsInstaller(latest) : null;
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

    if (!downloadsAvailable) return;

    const size = formatBytes(windowsInstaller.size_bytes);
    setText("[data-release-download-name]", windowsInstaller.name);
    setText("[data-release-download-size]", size);
    setText("[data-release-sha256]", windowsInstaller.sha256);

    document.querySelectorAll("[data-download-windows]").forEach((link) => {
      link.setAttribute("href", windowsInstaller.download_url);
      link.removeAttribute("aria-disabled");
      link.classList.remove("is-disabled");
    });
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
