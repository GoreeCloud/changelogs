"use strict";
(() => {
  const byId = id => document.getElementById(id);
  const connectForm = byId("connect-form");
  const connectPanel = byId("connect-panel");
  const library = byId("library");
  const list = byId("entries");
  const status = byId("status");
  const pageLabel = byId("page-label");
  const previous = byId("previous");
  const next = byId("next");
  let token = "";
  let offset = 0;
  let more = false;
  const limit = 20;
  const setStatus = text => { status.textContent = text; };
  const element = (tag, className, text) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined && text !== null) el.textContent = String(text);
    return el;
  };
  async function request(url) {
    const response = await fetch(url, {
      headers: { Authorization: "Bearer " + token },
      cache: "no-store", credentials: "omit"
    });
    if (response.status === 401) throw new Error("Invalid bearer token. Reconnect to continue.");
    if (!response.ok) throw new Error("Request failed (" + response.status + ").");
    return response.json();
  }
  const render = record => {
    const card = element("article", "entry glass");
    const top = element("div", "entry-top");
    top.append(element("span", "pill", record.kind), element("small", "", record.released_at));
    card.append(top, element("h3", "", record.title),
      element("p", "product", record.product + " · " + record.version));
    if (record.description) card.append(element("p", "description", record.description));
    const detail = element("details");
    detail.append(element("summary", "", "Entry details"));
    detail.append(element("p", "", "ID: " + record.id + " · Author: " + (record.author || "Not specified")));
    detail.append(element("p", "", "Created: " + record.created_at + " · Updated: " + record.updated_at));
    detail.append(element("pre", "", JSON.stringify(record.metadata || {}, null, 2)));
    card.append(detail);
    return card;
  };
  async function load() {
    if (!token) return;
    previous.disabled = true;
    next.disabled = true;
    setStatus("Loading changes…");
    try {
      const product = byId("product-input").value.trim();
      const query = byId("search-input").value.trim();
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (product) params.set("product", product);
      if (query) params.set("q", query);
      const data = await request((query ? "/v1/search?" : "/v1/entries?") + params.toString());
      list.replaceChildren();
      for (const item of data.entries) list.append(render(item));
      if (!data.entries.length) list.append(element("p", "empty glass", "No changes match these filters."));
      more = Boolean(data.has_more);
      previous.disabled = offset === 0;
      next.disabled = !more;
      pageLabel.textContent = "Page " + (offset / limit + 1);
      byId("result-count").textContent = data.entries.length + " changes in this page";
      setStatus("Connected to the local read-only API.");
    } catch (error) {
      list.replaceChildren();
      setStatus(error.message);
      if (error.message.startsWith("Invalid bearer")) disconnect();
    }
  }
  function disconnect() {
    token = "";
    offset = 0;
    list.replaceChildren();
    connectPanel.hidden = false;
    library.hidden = true;
    byId("token-input").value = "";
    setStatus("Disconnected. The token was cleared from this tab.");
  }
  connectForm.addEventListener("submit", async event => {
    event.preventDefault();
    token = byId("token-input").value;
    byId("token-input").value = "";
    try {
      await request("/health");
      connectPanel.hidden = true;
      library.hidden = false;
      offset = 0;
      await load();
    } catch (error) {
      token = "";
      setStatus(error.message);
    }
  });
  byId("disconnect").addEventListener("click", disconnect);
  byId("reload").addEventListener("click", load);
  byId("filter-form").addEventListener("submit", event => {
    event.preventDefault(); offset = 0; load();
  });
  previous.addEventListener("click", () => { if (offset >= limit) { offset -= limit; load(); } });
  next.addEventListener("click", () => { if (more) { offset += limit; load(); } });
})();
