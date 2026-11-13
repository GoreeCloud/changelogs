"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const status = message => { $("status").textContent = message; };
  const node = (tag, klass, value) => {
    const el = document.createElement(tag);
    if (klass) el.className = klass;
    if (value !== undefined) el.textContent = String(value);
    return el;
  };
  let username = "";
  let role = "";
  let csrf = "";
  let sessionEpoch = 0;
  let loadSequence = 0;
  let controller = null;
  let offset = 0;
  let hasMore = false;
  const limit = 30;

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin", cache: "no-store", redirect: "error",
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.method && options.method !== "GET" && csrf ?
          { "X-GoreeCloud-CSRF": csrf } : {}),
        ...(options.headers || {})
      }
    });
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(response.status === 401 ? "Sign in required." :
                              response.status === 403 ? "Access denied." :
                              "Server rejected the request.");
      error.status = response.status;
      throw error;
    }
    return result;
  }
  function clearSession() {
    ++sessionEpoch;
    ++loadSequence;
    if (controller) controller.abort();
    controller = null;
    username = ""; role = ""; csrf = "";
    offset = 0; hasMore = false;
    $("entries").replaceChildren();
    $("password").value = "";
    $("login-panel").hidden = false;
    $("workspace").hidden = true;
    $("next").disabled = true;
    $("previous").disabled = true;
  }
  function connected(value) {
    username = value.username;
    role = value.role;
    csrf = value.csrf || "";
    $("login-panel").hidden = true;
    $("workspace").hidden = false;
    $("whoami").textContent = "Signed in as " + username + " · " + role;
    $("create-section").hidden = role !== "admin";
    offset = 0;
    refresh();
  }
  function render(entries) {
    const fragment = document.createDocumentFragment();
    for (const entry of entries) {
      const card = node("article", "entry");
      const head = node("div", "entry-top");
      head.append(node("span", "kind", entry.kind), node("small", "", entry.released_at));
      card.append(head, node("h3", "", entry.title),
                  node("p", "", entry.product + " · " + entry.version));
      if (entry.description) card.append(node("p", "description", entry.description));
      fragment.append(card);
    }
    $("entries").replaceChildren(fragment);
    if (!entries.length) $("entries").append(node("p", "assist", "No matching changes."));
  }
  async function refresh() {
    if (!username) return;
    ++loadSequence;
    const sequence = loadSequence, epoch = sessionEpoch;
    if (controller) controller.abort();
    controller = new AbortController();
    $("previous").disabled = true; $("next").disabled = true;
    status("Loading shared changelogs…");
    try {
      const product = $("product").value.trim();
      const query = $("query").value.trim();
      const kind = $("kind").value;
      const params = new URLSearchParams({limit: String(limit), offset: String(offset)});
      if (product) params.set("product", product);
      if (kind) params.set("kind", kind);
      if (query) params.set("q", query);
      const path = query ? "/v1/search?" : "/v1/entries?";
      const data = await api(path + params.toString(), {signal: controller.signal});
      if (sequence !== loadSequence || epoch !== sessionEpoch) return;
      render(data.entries);
      hasMore = !!data.has_more;
      $("next").disabled = !hasMore;
      $("previous").disabled = offset === 0;
      $("page-label").textContent = "Page " + (Math.floor(offset / limit) + 1);
      $("results-title").textContent = data.entries.length + " changes on this page";
      status("Connected to your private server.");
    } catch (error) {
      if (sequence !== loadSequence || epoch !== sessionEpoch || error.name === "AbortError") return;
      if (error.status === 401) { clearSession(); status("Please sign in again."); return; }
      status(error.message);
    }
  }
  $("login-form").addEventListener("submit", async event => {
    event.preventDefault();
    const epoch = ++sessionEpoch;
    const usernameInput = $("username").value.trim();
    const password = $("password").value;
    $("password").value = "";
    status("Verifying account…");
    try {
      const result = await api("/v1/auth/session", {
        method: "POST", body: JSON.stringify({username: usernameInput, password})
      });
      if (epoch !== sessionEpoch) return;
      connected(result);
    } catch (error) {
      if (epoch !== sessionEpoch) return;
      status(error.message);
    }
  });
  $("logout").addEventListener("click", async () => {
    const saved = csrf;
    clearSession();
    status("Signed out locally.");
    try {
      await api("/v1/auth/logout", {
        method: "POST", body: "{}", headers: {"X-GoreeCloud-CSRF": saved}
      });
    } catch (_error) {
      // Local display is cleared even if a network logout cannot complete.
      status("Session cleared here; server logout could not be confirmed.");
    }
  });
  $("filters").addEventListener("submit", event => {
    event.preventDefault(); offset = 0; refresh();
  });
  $("reload").addEventListener("click", refresh);
  $("previous").addEventListener("click", () => {
    if (offset >= limit) { offset -= limit; refresh(); }
  });
  $("next").addEventListener("click", () => {
    if (hasMore && offset <= 1000000-limit) { offset += limit; refresh(); }
  });
  $("create-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (role !== "admin") return;
    const entry = {
      product: $("new-product").value.trim(), version: $("new-version").value.trim(),
      kind: $("new-kind").value, title: $("new-title").value.trim(),
      description: $("new-description").value
    };
    status("Saving change to server…");
    try {
      await api("/v1/entries", {method: "POST", body: JSON.stringify(entry)});
      $("create-form").reset();
      offset = 0; refresh();
    } catch (error) { status(error.message); }
  });
  api("/v1/me").then(connected).catch(() => { clearSession(); });
})();
