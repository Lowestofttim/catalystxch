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
    const status = metadata.downloads_enabled ? "Downloads available" : "Public links coming soon";
    const channel = latest.channel === "prerelease" ? "Prerelease" : "Stable";
    const meta = releaseDate
      ? `${channel} - published ${releaseDate} - ${status.toLowerCase()}`
      : `${channel} - ${status.toLowerCase()}`;

    setText("[data-release-version]", version);
    setText("[data-release-name]", latest.name || version);
    setText("[data-release-status]", status);
    setText("[data-release-meta]", meta);
    setText("[data-release-eyebrow]", `Public downloads coming soon - current beta ${version}`);
    setText("[data-release-date]", releaseDate ? `Released ${releaseDate}` : "");
    renderList("[data-release-notes]", latest.release_notes);
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
