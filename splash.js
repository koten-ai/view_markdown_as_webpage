(function () {
  "use strict";

  const recentEl = document.getElementById("recent");
  const recentEmpty = document.getElementById("recent-empty");
  const shortcutsEl = document.getElementById("shortcuts");
  const pathInput = document.getElementById("path-input");
  const pathForm = document.getElementById("path-form");
  const crumbsEl = document.getElementById("crumbs");
  const dirsEl = document.getElementById("dirs");
  const dirEmpty = document.getElementById("dir-empty");
  const mdCount = document.getElementById("md-count");
  const viewBtn = document.getElementById("view-btn");
  const errEl = document.getElementById("err");

  let currentPath = "";

  function showErr(msg) {
    errEl.hidden = !msg;
    errEl.textContent = msg || "";
  }

  async function getJson(url, opts) {
    const res = await fetch(url, opts);
    const data = await res.json().catch(function () { return {}; });
    if (!res.ok) {
      const err = new Error(data.error || res.statusText || "request failed");
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function renderRecent(items) {
    recentEl.innerHTML = "";
    const list = items || [];
    recentEmpty.hidden = list.length > 0;
    list.forEach(function (item) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "recent-item";
      const name = document.createElement("strong");
      name.textContent = item.name || item.path;
      const path = document.createElement("span");
      path.textContent = item.path;
      const meta = document.createElement("em");
      meta.textContent = item.md ? item.md + " markdown" : "Open";
      btn.appendChild(name);
      btn.appendChild(path);
      btn.appendChild(meta);
      btn.addEventListener("click", function () {
        openFolder(item.path);
      });
      recentEl.appendChild(btn);
    });
  }

  function renderShortcuts(items) {
    shortcutsEl.innerHTML = "";
    (items || []).forEach(function (item) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip";
      btn.textContent = item.name || item.path;
      btn.addEventListener("click", function () {
        browse(item.path);
      });
      shortcutsEl.appendChild(btn);
    });
  }

  function renderCrumbs(path, parent) {
    crumbsEl.innerHTML = "";
    const parts = path.split("/").filter(Boolean);
    const rootBtn = document.createElement("button");
    rootBtn.type = "button";
    rootBtn.textContent = path.charAt(0) === "/" ? "/" : parts[0] || path;
    rootBtn.addEventListener("click", function () {
      browse(path.charAt(0) === "/" ? "/" : parts[0]);
    });
    crumbsEl.appendChild(rootBtn);
    let acc = path.charAt(0) === "/" ? "" : "";
    if (path.charAt(0) === "/") {
      acc = "";
      parts.forEach(function (part) {
        acc += "/" + part;
        const here = acc;
        const sep = document.createElement("span");
        sep.textContent = "/";
        crumbsEl.appendChild(sep);
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = part;
        b.addEventListener("click", function () {
          browse(here);
        });
        crumbsEl.appendChild(b);
      });
    }
    if (parent && parent !== path) {
      const up = document.createElement("button");
      up.type = "button";
      up.className = "up";
      up.textContent = "Up";
      up.addEventListener("click", function () {
        browse(parent);
      });
      crumbsEl.appendChild(up);
    }
  }

  function renderDirs(dirs) {
    dirsEl.innerHTML = "";
    dirEmpty.hidden = dirs.length > 0;
    dirs.forEach(function (d) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "dir-row";
      const name = document.createElement("strong");
      name.textContent = d.name;
      const meta = document.createElement("span");
      meta.textContent = d.md ? d.md + " md" : "";
      btn.appendChild(name);
      btn.appendChild(meta);
      btn.addEventListener("click", function () {
        browse(d.path);
      });
      dirsEl.appendChild(btn);
    });
  }

  async function browse(path) {
    showErr("");
    try {
      const data = await getJson("/api/fs?path=" + encodeURIComponent(path || ""));
      currentPath = data.path;
      pathInput.value = data.path;
      renderCrumbs(data.path, data.parent);
      renderDirs(data.dirs || []);
      const n = data.md || 0;
      const files = data.files || [];
      mdCount.textContent = n
        ? n + " markdown file" + (n === 1 ? "" : "s") + " in this folder"
        : files.length
          ? files.length + " other files here"
          : "No markdown in this folder (subfolders may still have notes)";
      viewBtn.disabled = false;
    } catch (err) {
      showErr(err.message || String(err));
    }
  }

  async function openFolder(path) {
    showErr("");
    viewBtn.disabled = true;
    try {
      await getJson("/api/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path }),
      });
      location.href = "/viewer.html";
    } catch (err) {
      viewBtn.disabled = false;
      showErr(err.message || String(err));
    }
  }

  pathForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    browse(pathInput.value.trim());
  });
  viewBtn.addEventListener("click", function () {
    if (currentPath) openFolder(currentPath);
  });

  async function boot() {
    try {
      const state = await getJson("/api/state");
      renderRecent(state.recent || []);
      renderShortcuts(state.shortcuts || []);
      const start = state.last || (state.shortcuts[0] && state.shortcuts[0].path) || state.start_dir || "";
      await browse(start);
    } catch (err) {
      showErr("This page needs the local server. Run python3 serve.py then open http://127.0.0.1:8765");
    }
  }

  boot();
})();
