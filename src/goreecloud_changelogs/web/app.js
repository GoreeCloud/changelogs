"use strict";
(() => {
  // No token, user data or session state is written to storage or URLs.
  const byId = id => document.getElementById(id);
  const connectForm = byId("connect-form");
  const connectPanel = byId("connect-panel");
  const library = byId("library");
  const list = byId("entries");
  const status = byId("status");
  const pageLabel = byId("page-label");
  const previous = byId("previous");
  const next = byId("next");
  const searchLabel = byId("search-label");
  const clearVersion = byId("clear-version");
  const entriesButton = byId("view-entries");
  const releasesButton = byId("view-releases");
  const limit = 20;

  let token = "";
  let mode = "entries";
  let versionFilter = "";
  let offset = 0;
  let more = false;
  let sessionEpoch = 0;
  let requestSequence = 0;
  let activeController = null;

  const setStatus = value => { status.textContent = value; };
  const element = (tag, className, value) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = String(value);
    return node;
  };
  async function api(path, suppliedToken, signal) {
    const response = await fetch(path, {
      method: "GET",
      headers: { Authorization: "Bearer " + suppliedToken },
      signal,
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
    });
    if (response.status === 401) throw new Error("Invalid bearer token. Reconnect to continue.");
    if (!response.ok) throw new Error("Request failed (" + response.status + ").");
    return response.json();
  }
  function abortRequest() {
    if (activeController) activeController.abort();
    activeController = null;
  }
  function disconnect() {
    ++sessionEpoch;
    ++requestSequence;
    abortRequest();
    token = "";
    offset = 0;
    more = false;
    versionFilter = "";
    list.replaceChildren();
    byId("token-input").value = "";
    connectPanel.hidden = false;
    library.hidden = true;
    previous.disabled = true;
    next.disabled = true;
    setStatus("Disconnected. Pending responses cannot restore the session.");
  }
  const renderEntry = record => {
    const card = element("article", "entry glass");
    const top = element("div", "entry-top");
    top.append(element("span", "pill", record.kind),
               element("small", "", record.released_at));
    card.append(top, element("h3", "", record.title),
      element("p", "product", record.product + " · " + record.version));
    if (record.description) card.append(element("p", "description", record.description));
    const detail = element("details");
    detail.append(element("summary", "", "Entry details"));
    detail.append(element("p", "", "ID: " + record.id + " · Author: " +
                                       (record.author || "Not specified")));
    detail.append(element("p", "", "Created: " + record.created_at +
                                     " · Updated: " + record.updated_at));
    detail.append(element("pre", "", JSON.stringify(record.metadata || {}, null, 2)));
    card.append(detail);
    return card;
  };
  const renderRelease = record => {
    const card = element("article", "entry glass");
    const top = element("div", "entry-top");
    top.append(element("span", "pill", record.version),
               element("small", "", record.released_at));
    card.append(top, element("h3", "", record.product),
      element("p", "product", record.entries + " changes · " +
                               record.first_released_at + "–" + record.released_at));
    const tags = element("div", "kind-tags");
    for (const [kind, count] of Object.entries(record.by_kind || {})) {
      tags.append(element("span", "kind-tag", kind + " " + count));
    }
    card.append(tags);
    const view = element("button", "quiet release-action", "View changes");
    view.type = "button";
    view.addEventListener("click", () => {
      byId("product-input").value = record.product;
      byId("search-input").value = "";
      versionFilter = record.version;
      selectMode("entries");
    });
    card.append(view);
    return card;
  };
  function selectMode(nextMode) {
    mode = nextMode;
    offset = 0;
    if (mode === "releases") versionFilter = "";
    searchLabel.hidden = mode === "releases";
    byId("search-input").disabled = mode === "releases";
    entriesButton.setAttribute("aria-pressed", String(mode === "entries"));
    releasesButton.setAttribute("aria-pressed", String(mode === "releases"));
    byId("library-title").textContent = mode === "entries" ? "Change history" : "Release history";
    clearVersion.hidden = mode !== "entries" || !versionFilter;
    load();
  }
  async function load() {
    if (!token) return;
    const epoch = sessionEpoch;
    const sequence = ++requestSequence;
    const suppliedToken = token;
    abortRequest();
    const controller = new AbortController();
    activeController = controller;
    previous.disabled = true;
    next.disabled = true;
    setStatus("Loading " + (mode === "entries" ? "changes" : "releases") + "…");
    try {
      const product = byId("product-input").value.trim();
      const query = mode === "entries" ? byId("search-input").value.trim() : "";
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (product) params.set("product", product);
      let path = "/v1/releases?";
      if (mode === "entries") {
        path = query ? "/v1/search?" : "/v1/entries?";
        if (query) params.set("q", query);
        if (!query && versionFilter) params.set("version", versionFilter);
      }
      const data = await api(path + params.toString(), suppliedToken, controller.signal);
      // Even a completed or unabortable fetch must not re-display private data.
      if (epoch !== sessionEpoch || sequence !== requestSequence || !token) return;
      const rows = mode === "entries" ? data.entries : data.releases;
      list.replaceChildren();
      for (const item of rows) list.append(mode === "entries" ? renderEntry(item) : renderRelease(item));
      if (!rows.length) list.append(element("p", "empty glass", "No matching records."));
      more = Boolean(data.has_more);
      previous.disabled = offset === 0;
      next.disabled = !more;
      pageLabel.textContent = "Page " + (offset / limit + 1);
      clearVersion.hidden = mode !== "entries" || !versionFilter;
      byId("result-count").textContent = rows.length +
        (mode === "entries" ? " changes" : " releases") + " on this page" +
        (versionFilter ? " · Version: " + versionFilter : "");
      setStatus("Connected to the local read-only API.");
    } catch (error) {
      if (epoch !== sessionEpoch || sequence !== requestSequence || !token) return;
      if (error.name === "AbortError") return;
      list.replaceChildren();
      previous.disabled = true;
      next.disabled = true;
      if (error.message.startsWith("Invalid bearer token")) {
        disconnect();
      } else {
        setStatus(error.message || "Request failed.");
      }
    }
  }

  connectForm.addEventListener("submit", async event => {
    event.preventDefault();
    ++sessionEpoch;
    ++requestSequence;
    abortRequest();
    const epoch = sessionEpoch;
    const candidate = byId("token-input").value;
    byId("token-input").value = "";
    if (candidate.length < 32) { setStatus("A 32+ character token is required."); return; }
    const controller = new AbortController();
    activeController = controller;
    setStatus("Checking local connection…");
    try {
      await api("/health", candidate, controller.signal);
      if (epoch !== sessionEpoch) return;
      token = candidate;
      connectPanel.hidden = true;
      library.hidden = false;
      offset = 0;
      selectMode("entries");
    } catch (error) {
      if (epoch !== sessionEpoch || error.name === "AbortError") return;
      token = "";
      setStatus(error.message || "Unable to connect.");
    }
  });
  byId("disconnect").addEventListener("click", disconnect);
  byId("reload").addEventListener("click", load);
  byId("filter-form").addEventListener("submit", event => {
    event.preventDefault();
    versionFilter = "";
    offset = 0;
    load();
  });
  clearVersion.addEventListener("click", () => { versionFilter = ""; offset = 0; load(); });
  entriesButton.addEventListener("click", () => selectMode("entries"));
  releasesButton.addEventListener("click", () => selectMode("releases"));
  previous.addEventListener("click", () => { if (offset >= limit) { offset -= limit; load(); } });
  next.addEventListener("click", () => {
    if (more && offset <= 1000000 - limit) { offset += limit; load(); }
  });
})();
