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
  let viewMode = "entries";
  let versionFilter = "";
  const limit = 30;
  let saving = false;
  let logoutPending = false;
  const setSaveStatus = (message, state = "") => {
    const target = $("save-status");
    target.textContent = message;
    if (state) target.dataset.state = state;
    else delete target.dataset.state;
  };

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
    viewMode = "entries"; versionFilter = "";
    $("entries").replaceChildren();
    $("password").value = "";
    $("create-form").reset();
    $("filters").reset();
    $("create-section").hidden = true;
    $("jump-create").hidden = true;
    document.body.classList.remove("is-authenticated");
    setSaveStatus("");
    saving = false;
    $("save-submit").disabled = false;
    $("create-form").removeAttribute("aria-busy");
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
    $("jump-create").hidden = role !== "admin";
    document.body.classList.add("is-authenticated");
    setSaveStatus("");
    offset = 0;
    setView("entries", false);
    refresh();
  }
  function renderRelease(release) {
    const card = node("article", "entry");
    const head = node("div", "entry-top");
    head.append(node("span", "kind", release.version),
                node("small", "", release.released_at));
    const count = Number(release.entries) || 0;
    const dates = release.first_released_at === release.released_at
      ? release.released_at
      : release.first_released_at + " to " + release.released_at;
    card.append(head, node("h3", "", release.product),
                node("p", "release-details", count + " " +
                  (count === 1 ? "change" : "changes") + " · " + dates));
    const kinds = node("div", "release-kinds");
    for (const [kind, count] of Object.entries(release.by_kind || {})) {
      kinds.append(node("span", "release-kind", kind + ": " + count));
    }
    card.append(kinds);
    const open = node("button", "secondary release-open", "View changes");
    open.type = "button";
    open.addEventListener("click", () => {
      $("product").value = release.product;
      $("query").value = "";
      $("kind").value = "";
      versionFilter = release.version;
      setView("entries");
    });
    card.append(open);
    return card;
  }
  function setView(nextMode, reload = true) {
    viewMode = nextMode;
    offset = 0;
    if (nextMode === "releases") versionFilter = "";
    $("view-entries").setAttribute("aria-pressed", String(nextMode === "entries"));
    $("view-releases").setAttribute("aria-pressed", String(nextMode === "releases"));
    $("search-label").hidden = nextMode === "releases";
    $("kind-label").hidden = nextMode === "releases";
    $("query").disabled = nextMode === "releases";
    $("kind").disabled = nextMode === "releases";
    $("clear-version").hidden = nextMode !== "entries" || !versionFilter;
    if (reload) refresh();
  }
  function render(entries, mode) {
    const fragment = document.createDocumentFragment();
    for (const entry of entries) {
      if (mode === "releases") {
        fragment.append(renderRelease(entry));
        continue;
      }
      const card = node("article", "entry");
      const head = node("div", "entry-top");
      head.append(node("span", "kind", entry.kind), node("small", "", entry.released_at));
      card.append(head, node("h3", "", entry.title),
                  node("p", "", entry.product + " · " + entry.version));
      if (entry.description) card.append(node("p", "description", entry.description));
      fragment.append(card);
    }
    $("entries").replaceChildren(fragment);
    if (!entries.length) $("entries").append(node("p", "assist",
      mode === "releases" ? "No matching releases." : "No matching changes."));
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
      const mode = viewMode;
      const query = mode === "entries" ? $("query").value.trim() : "";
      const kind = mode === "entries" ? $("kind").value : "";
      const params = new URLSearchParams({limit: String(limit), offset: String(offset)});
      if (product) params.set("product", product);
      let path = "/v1/releases?";
      if (mode === "entries") {
        path = query ? "/v1/search?" : "/v1/entries?";
        if (query) params.set("q", query);
        if (kind) params.set("kind", kind);
        if (!query && versionFilter) params.set("version", versionFilter);
      }
      const data = await api(path + params.toString(), {signal: controller.signal});
      if (sequence !== loadSequence || epoch !== sessionEpoch) return;
      const rows = mode === "releases" ? data.releases : data.entries;
      render(rows, mode);
      hasMore = !!data.has_more;
      $("next").disabled = !hasMore;
      $("previous").disabled = offset === 0;
      $("page-label").textContent = "Page " + (Math.floor(offset / limit) + 1);
      const count = rows.length;
      const singular = mode === "entries" ? "change" : "release";
      $("results-title").textContent = count + " " +
        (count === 1 ? singular : singular + "s") + " on this page" +
        (mode === "entries" && versionFilter ? " · Version: " + versionFilter : "");
      $("clear-version").hidden = mode !== "entries" || !versionFilter;
      status("Connected to your private server.");
    } catch (error) {
      if (sequence !== loadSequence || epoch !== sessionEpoch || error.name === "AbortError") return;
      if (error.status === 401) { clearSession(); status("Please sign in again."); return; }
      status(error.message);
    }
  }
  $("login-form").addEventListener("submit", async event => {
    event.preventDefault();
    // An in-flight Set-Cookie from logout must not race a fresh login.
    if (logoutPending) return;
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
    if (logoutPending) return;
    const saved = csrf;
    clearSession();
    const epoch = sessionEpoch;
    logoutPending = true;
    $("login-submit").disabled = true;
    status("Signed out locally. Revoking server session…");
    const abort = new AbortController();
    const deadline = setTimeout(() => abort.abort(), 8000);
    try {
      await api("/v1/auth/logout", {
        method: "POST", body: "{}", signal: abort.signal,
        headers: {"X-GoreeCloud-CSRF": saved}
      });
      if (epoch === sessionEpoch) status("Signed out. Server session revoked.");
    } catch (_error) {
      // Never let an old logout failure overwrite a different session.
      if (epoch === sessionEpoch) {
        status("Session cleared here; server logout could not be confirmed.");
      }
    } finally {
      clearTimeout(deadline);
      logoutPending = false;
      $("login-submit").disabled = false;
    }
  });
  $("filters").addEventListener("submit", event => {
    event.preventDefault(); versionFilter = ""; offset = 0; refresh();
  });
  $("view-entries").addEventListener("click", () => setView("entries"));
  $("view-releases").addEventListener("click", () => setView("releases"));
  $("clear-version").addEventListener("click", () => {
    versionFilter = ""; offset = 0; refresh();
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
    if (role !== "admin" || saving) return;
    const epoch = sessionEpoch;
    const entry = {
      product: $("new-product").value.trim(), version: $("new-version").value.trim(),
      kind: $("new-kind").value, title: $("new-title").value.trim(),
      description: $("new-description").value
    };
    saving = true;
    $("save-submit").disabled = true;
    $("create-form").setAttribute("aria-busy", "true");
    setSaveStatus("Saving change…");
    try {
      await api("/v1/entries", {method: "POST", body: JSON.stringify(entry)});
      if (epoch !== sessionEpoch) return;
      $("create-form").reset();
      offset = 0;
      setSaveStatus("Change saved to the server.", "success");
      await refresh();
    } catch (error) {
      if (epoch === sessionEpoch) {
        setSaveStatus(error.message || "Unable to save the change.", "error");
      }
    } finally {
      if (epoch === sessionEpoch) {
        saving = false;
        $("save-submit").disabled = false;
        $("create-form").removeAttribute("aria-busy");
      }
    }
  });
  const initialEpoch = sessionEpoch;
  api("/v1/me").then(result => {
    if (initialEpoch === sessionEpoch) connected(result);
  }).catch(() => {
    if (initialEpoch === sessionEpoch) clearSession();
  });
})();
