"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const appPath = path.join(__dirname, "..", "src", "goreecloud_changelogs",
                          "hosted_web", "app.js");

function response(value, status = 200) {
  return {ok: status >= 200 && status < 300, status,
          json: async () => value};
}

function harness() {
  const nodes = new Map();
  const calls = [];
  let finishLogout;
  class Node {
    constructor(tag) {
      this.tagName = tag;
      this.children = [];
      this.listeners = {};
      this.attributes = {};
      this.dataset = {};
      this.value = "";
      this.textContent = "";
      this.hidden = false;
      this.disabled = false;
      this.classList = {add() {}, remove() {}};
    }
    addEventListener(type, callback) {this.listeners[type] = callback;}
    setAttribute(key, value) {this.attributes[key] = value;}
    removeAttribute(key) {delete this.attributes[key];}
    append(...children) {this.children.push(...children);}
    replaceChildren(...children) {
      this.children = children.flatMap(child =>
        child && child.tagName === "#fragment" ? child.children : [child]);
    }
    reset() {}
    click() {
      if (!this.listeners.click) throw new Error("Missing click listener");
      return this.listeners.click({preventDefault() {}});
    }
    submit() {
      if (!this.listeners.submit) throw new Error("Missing submit listener");
      return this.listeners.submit({preventDefault() {}});
    }
  }
  function byId(id) {
    if (!nodes.has(id)) nodes.set(id, new Node(id));
    return nodes.get(id);
  }
  const document = {
    getElementById: byId,
    createElement: tag => new Node(tag),
    createDocumentFragment: () => new Node("#fragment"),
    body: new Node("body")
  };
  const fetch = (url, options) => {
    calls.push({url, options});
    if (url === "/v1/me") {
      return Promise.resolve(response({username: "admin", role: "admin",
                                       csrf: "mock-csrf"}));
    }
    if (url.startsWith("/v1/releases?")) {
      return Promise.resolve(response({
        releases: [{product: "mesh", version: "1.0",
                    released_at: "2026-11-13", first_released_at: "2026-11-12",
                    entries: 2, by_kind: {added: 1, fixed: 1}}],
        has_more: false
      }));
    }
    if (url.startsWith("/v1/entries?") || url.startsWith("/v1/search?")) {
      return Promise.resolve(response({entries: [
        {id: 1, product: "goreecloud-notes", version: "0.1.10-dev", kind: "fixed",
         title: "Merged source fix", description: "", released_at: "2026-11-13",
         metadata: {distribution_status: "development-source-only"}},
        {id: 2, product: "mesh", version: "1.0", kind: "added",
         title: "Verified", description: "", released_at: "2026-11-13"}
      ], has_more: false}));
    }
    if (url === "/v1/auth/logout") {
      return new Promise(resolve => { finishLogout = resolve; });
    }
    if (url === "/v1/auth/session") {
      return Promise.resolve(response({username: "admin", role: "admin",
                                       csrf: "mock-csrf"}));
    }
    throw new Error("Unexpected request: " + url);
  };
  vm.runInNewContext(fs.readFileSync(appPath, "utf8"),
    {document, fetch, AbortController, URLSearchParams,
     setTimeout, clearTimeout}, {filename: "hosted_web/app.js"});
  return {byId, calls, finishLogout: () => finishLogout};
}

async function tick() {
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
}

function findButton(root, text) {
  if (root.tagName === "button" && root.textContent === text) return root;
  for (const child of root.children) {
    const result = findButton(child, text);
    if (result) return result;
  }
  return null;
}

test("logout disables new login until cookie revocation completes", async () => {
  const h = harness();
  await tick();
  assert.equal(h.byId("workspace").hidden, false);
  h.byId("logout").click();
  assert.equal(h.byId("login-submit").disabled, true);
  assert.equal(h.byId("workspace").hidden, true);
  assert.equal(h.byId("entries").children.length, 0);
  h.byId("username").value = "admin";
  h.byId("password").value = "attempt-during-logout";
  h.byId("login-form").submit();
  assert.equal(h.calls.filter(call => call.url === "/v1/auth/session").length, 0);
  assert.equal(h.calls.filter(call => call.url === "/v1/auth/logout").length, 1);
  h.finishLogout()(response({logged_out: true}));
  await tick();
  assert.equal(h.byId("login-submit").disabled, false);
  assert.match(h.byId("status").textContent, /Server session revoked/);
});

test("release view drills into matching product and version without writes", async () => {
  const h = harness();
  await tick();
  h.byId("view-releases").click();
  await tick();
  assert.equal(h.byId("view-releases").attributes["aria-pressed"], "true");
  assert.ok(h.calls.some(call => call.url.startsWith("/v1/releases?")));
  const open = findButton(h.byId("entries"), "View changes");
  assert.ok(open, "release drill-down action is rendered");
  open.click();
  await tick();
  assert.equal(h.byId("product").value, "mesh");
  assert.ok(h.calls.some(call =>
    call.url.startsWith("/v1/entries?") && call.url.includes("version=1.0") &&
    call.url.includes("product=mesh")));
  assert.equal(h.byId("view-entries").attributes["aria-pressed"], "true");
  assert.ok(h.calls.every(call => !call.options.method ||
                                  call.options.method === "GET"));
});

function flattenText(root) {
  return [root.textContent, ...root.children.flatMap(flattenText)].join(" ");
}

test("development-source-only records are visibly marked and unknown status is not asserted", async () => {
  const h = harness();
  await tick();
  const entries = h.byId("entries").children;
  assert.equal(entries.length, 2);
  assert.match(flattenText(entries[0]), /Unreleased · development source/);
  assert.doesNotMatch(flattenText(entries[1]), /Unreleased/);
});

test("grouped versions never assert a published release", async () => {
  const h = harness();
  await tick();
  h.byId("view-releases").click();
  await tick();
  assert.match(flattenText(h.byId("entries")), /publication not verified/);
});
