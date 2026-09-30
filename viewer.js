/* global marked, mermaid, renderMathInElement */
(function () {
  "use strict";

  const article = document.getElementById("doc");
  const appEl = document.querySelector(".app");
  const navEl = document.getElementById("nav");
  const navList = document.getElementById("nav-list");
  const navEmpty = document.getElementById("nav-empty");
  const filterInput = document.getElementById("nav-filter");
  const navAll = document.getElementById("nav-all");
  const crumb = document.getElementById("crumb");
  const brand = document.getElementById("brand");
  const brandName = brand.querySelector(".logo-name");
  const toggle = document.getElementById("nav-toggle");
  const zenBtn = document.getElementById("zen-toggle");
  const progressEl = document.getElementById("progress");
  const toTop = document.getElementById("to-top");
  const scrim = document.getElementById("scrim");
  const lightbox = document.getElementById("lightbox");
  const lbStage = document.getElementById("lb-stage");
  const lbCap = document.getElementById("lb-cap");
  const peekEl = document.getElementById("peek");
  const TYPE_MAX = 3;
  const TYPE_KEY = "mdview-type";
  const ZEN_KEY = "mdview-zen";
  const FOLD_KEY = "mdview-fold";

  const MD_RE = /\.(md|markdown|mdown|mkd)(?:$|[?#])/i;
  const IMAGE_RE = /\.(png|jpe?g|gif|webp|avif|svg|bmp|ico|tiff?|heic|heif)(?:$|[?#])/i;
  const VIDEO_RE = /\.(mp4|webm|ogv|mov|m4v)(?:$|[?#])/i;
  const AUDIO_RE = /\.(mp3|wav|ogg|m4a|flac|aac)(?:$|[?#])/i;
  const PDF_RE = /\.pdf(?:$|[?#])/i;
  const TEXT_RE = /\.(txt|csv|tsv|json|ya?ml|xml|log|rst|adoc|html?|css|js|ts)(?:$|[?#])/i;

  let notes = [];
  let folderTitle = "Markdown";
  let folderKey = "";
  let defaultDoc = "README.md";
  let currentPath = defaultDoc;

  marked.setOptions({ gfm: true, breaks: false });
  mermaid.initialize({
    startOnLoad: false,
    theme: "neutral",
    securityLevel: "loose",
    fontFamily: "Inter, sans-serif",
    themeVariables: {
      primaryColor: "#e7f7fd",
      primaryTextColor: "#1f2a38",
      lineColor: "#7b8898",
      secondaryColor: "#f5f8fb",
      tertiaryColor: "#ffffff",
    },
  });

  function dirOf(path) {
    const i = path.lastIndexOf("/");
    return i === -1 ? "" : path.slice(0, i + 1);
  }

  function extOf(path) {
    const clean = (path || "").split("?")[0].split("#")[0];
    const i = clean.lastIndexOf(".");
    return i === -1 ? "" : clean.slice(i + 1).toLowerCase();
  }

  function fileKind(path) {
    if (MD_RE.test(path)) return "md";
    if (IMAGE_RE.test(path)) return "image";
    if (VIDEO_RE.test(path)) return "video";
    if (AUDIO_RE.test(path)) return "audio";
    if (PDF_RE.test(path)) return "pdf";
    if (TEXT_RE.test(path)) return "text";
    return "other";
  }

  function extractMath(md) {
    const slots = [];
    const out = md.replace(/\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)/g, function (match) {
      const i = slots.length;
      slots.push(match);
      return "<!--GRMATH" + i + "-->";
    });
    return { md: out, slots: slots };
  }

  function restoreMath(html, slots) {
    return html.replace(/<!--GRMATH(\d+)-->/g, function (_, n) {
      return slots[Number(n)];
    });
  }

  function encodePath(path) {
    return path.split("/").map(encodeURIComponent).join("/");
  }

  function githubSlug(text) {
    return text
      .trim()
      .toLowerCase()
      .replace(/[^\p{L}\p{N}\s-]/gu, "")
      .replace(/\s+/g, "-");
  }

  function headingLabel(h) {
    const clone = h.cloneNode(true);
    clone.querySelectorAll(".h-anchor").forEach(function (el) {
      el.remove();
    });
    return (clone.textContent || "").trim();
  }

  function slugHeadings(root) {
    const seen = Object.create(null);
    root.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach(function (h) {
      if (h.id) return;
      let slug = githubSlug(headingLabel(h) || "section");
      if (!slug) slug = "section";
      if (seen[slug]) {
        seen[slug] += 1;
        slug = slug + "-" + seen[slug];
      } else {
        seen[slug] = 0;
      }
      h.id = slug;
    });
  }

  function addHeadingAnchors(root) {
    root.querySelectorAll("h1, h2, h3, h4").forEach(function (h) {
      if (!h.id || h.querySelector(".h-anchor")) return;
      const a = document.createElement("a");
      a.className = "h-anchor";
      a.href = "#" + h.id;
      a.textContent = "#";
      a.setAttribute("aria-label", "Link to this section");
      h.appendChild(a);
    });
  }

  function insertToc(root) {
    const heads = Array.prototype.slice.call(root.querySelectorAll("h2, h3"));
    if (heads.length < 2) return;
    const nav = document.createElement("nav");
    nav.className = "toc";
    nav.setAttribute("aria-label", "On this page");
    const k = document.createElement("p");
    k.className = "toc-kicker";
    k.textContent = "On this page";
    nav.appendChild(k);
    const ul = document.createElement("ul");
    heads.forEach(function (h) {
      if (!h.id) return;
      const li = document.createElement("li");
      if (h.tagName === "H3") li.className = "toc-h3";
      const a = document.createElement("a");
      a.href = "#" + h.id;
      a.textContent = headingLabel(h);
      li.appendChild(a);
      ul.appendChild(li);
    });
    nav.appendChild(ul);
    const h1 = root.querySelector("h1");
    if (h1 && h1.nextSibling) h1.parentNode.insertBefore(nav, h1.nextSibling);
    else root.insertBefore(nav, root.firstChild);
  }

  function wrapTables(root) {
    root.querySelectorAll("table").forEach(function (table) {
      if (table.parentElement && table.parentElement.classList.contains("table-wrap")) return;
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
    });
  }

  function fallbackCopy(text, ok) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      ok();
    } catch (e) { /* ignore */ }
    ta.remove();
  }

  function wrapCode(root) {
    root.querySelectorAll("pre").forEach(function (pre) {
      if (pre.parentElement && pre.parentElement.classList.contains("code-wrap")) return;
      const wrap = document.createElement("div");
      wrap.className = "code-wrap";
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy-btn";
      btn.textContent = "Copy";
      btn.addEventListener("click", function () {
        const text = pre.textContent || "";
        function ok() {
          btn.textContent = "Copied";
          setTimeout(function () {
            btn.textContent = "Copy";
          }, 1400);
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(ok).catch(function () {
            fallbackCopy(text, ok);
          });
        } else {
          fallbackCopy(text, ok);
        }
      });
      wrap.appendChild(btn);
    });
  }

  function classify(href, current) {
    if (!href || href.startsWith("javascript:")) return { kind: "skip" };
    if (href.startsWith("mailto:") || href.startsWith("tel:")) return { kind: "ext", url: href, host: href.split(":")[0] };
    if (href.startsWith("#")) return { kind: "hash", hash: href.slice(1) };
    if (/^https?:\/\//i.test(href) || href.startsWith("//")) {
      try {
        const abs = new URL(href, location.href);
        return { kind: "ext", url: abs.href, host: abs.hostname.replace(/^www\./, "") };
      } catch (e) {
        return { kind: "skip" };
      }
    }
    try {
      const base = "https://notes.local/" + dirOf(current);
      const u = new URL(href, base);
      const path = decodeURIComponent(u.pathname.replace(/^\//, ""));
      const hash = (u.hash || "").replace(/^#/, "");
      const kind = fileKind(path);
      if (kind === "md") return { kind: "local", path: path, hash: hash };
      return { kind: "file", path: path, file: kind, hash: hash };
    } catch (e) {
      return { kind: "skip" };
    }
  }

  function decorateLinks(root, current) {
    root.querySelectorAll("a[href]").forEach(function (a) {
      const href = a.getAttribute("href");
      const info = classify(href, current);
      if (info.kind === "skip" || info.kind === "hash") return;
      if (info.kind === "local") {
        a.classList.add("link-local");
        const next = "?doc=" + encodeURIComponent(info.path) + (info.hash ? "#" + info.hash : "");
        a.setAttribute("href", next);
        a.addEventListener("click", function (ev) {
          if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button !== 0) return;
          ev.preventDefault();
          closeNav();
          loadDoc(info.path, info.hash, false);
        });
        return;
      }
      if (info.kind === "file") {
        a.classList.add("link-file");
        const url = "/" + encodePath(info.path);
        a.setAttribute("href", url);
        if (!a.querySelector(".file-kind") && info.file && info.file !== "other") {
          const chip = document.createElement("span");
          chip.className = "file-kind";
          chip.textContent = extOf(info.path) || info.file;
          a.appendChild(chip);
        }
        a.addEventListener("click", function (ev) {
          if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button !== 0) return;
          if (info.file === "image" || info.file === "video" || info.file === "pdf") {
            ev.preventDefault();
            openLightbox({ type: info.file, src: url, alt: a.textContent.replace(/\s+\w+$/, "").trim() });
          }
        });
        return;
      }
      if (info.kind === "ext") {
        a.classList.add("link-ext");
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noopener noreferrer");
        if (info.host && !a.querySelector(".ext-host")) {
          const chip = document.createElement("span");
          chip.className = "ext-host";
          chip.textContent = info.host;
          a.appendChild(chip);
        }
      }
    });
  }

  const peekCache = Object.create(null);
  let peekTimer = 0;
  let peekHideTimer = 0;
  let peekGen = 0;
  let peekAnchor = null;

  function canHoverPeek() {
    return window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  }

  function hidePeek() {
    clearTimeout(peekTimer);
    clearTimeout(peekHideTimer);
    peekAnchor = null;
    if (peekEl) peekEl.hidden = true;
  }

  function scheduleHidePeek() {
    clearTimeout(peekHideTimer);
    peekHideTimer = setTimeout(hidePeek, 160);
  }

  function sanitizePeekHtml(html) {
    const tmp = document.createElement("div");
    tmp.innerHTML = html;
    tmp.querySelectorAll("script, iframe, object, embed, form, video, audio, style, .h-anchor").forEach(function (el) {
      el.remove();
    });
    tmp.querySelectorAll("*").forEach(function (el) {
      Array.prototype.slice.call(el.attributes).forEach(function (attr) {
        if (/^on/i.test(attr.name) || ((attr.name === "href" || attr.name === "src") && /^\s*javascript:/i.test(attr.value))) {
          el.removeAttribute(attr.name);
        }
      });
    });
    tmp.querySelectorAll("a").forEach(function (a) {
      a.setAttribute("tabindex", "-1");
    });
    tmp.querySelectorAll("img").forEach(function (img, i) {
      if (i > 0) img.remove();
    });
    tmp.querySelectorAll("table").forEach(function (table, i) {
      if (i > 0) {
        table.remove();
        return;
      }
      table.querySelectorAll("tr").forEach(function (row, j) {
        if (j > 4) row.remove();
      });
    });
    tmp.querySelectorAll("pre, .mermaid, .toc").forEach(function (el) {
      el.remove();
    });
    return tmp.innerHTML;
  }

  function mdWindow(md, hash) {
    const lines = md.split(/\r?\n/);
    let start = 0;
    let title = "";
    let level = 1;
    if (hash) {
      for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
        if (!m) continue;
        if (githubSlug(m[2]) === hash) {
          start = i;
          title = m[2].trim();
          level = m[1].length;
          break;
        }
      }
    }
    if (!title) {
      for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(/^#\s+(.+)$/);
        if (m) {
          title = m[1].trim();
          start = i;
          break;
        }
      }
    }
    const chunk = [];
    let chars = 0;
    for (let i = start; i < lines.length; i++) {
      if (i === start && title && /^#{1,6}\s+/.test(lines[i])) continue;
      if (i > start) {
        const m = lines[i].match(/^(#{1,6})\s+/);
        if (m && hash && m[1].length <= level) break;
        if (m && !hash && m[1].length === 1) break;
      }
      chunk.push(lines[i]);
      chars += lines[i].length;
      if (chars > 900 && chunk.length > 6) break;
    }
    return { title: title, md: chunk.join("\n").replace(/```[\s\S]*?```/g, "") };
  }

  function htmlFromSection(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    const wrap = document.createElement("div");
    let n = el.nextElementSibling;
    let count = 0;
    while (n && count < 6) {
      if (/^H[1-6]$/.test(n.tagName)) break;
      if (n.classList && (n.classList.contains("toc") || n.classList.contains("code-wrap"))) {
        n = n.nextElementSibling;
        continue;
      }
      wrap.appendChild(n.cloneNode(true));
      count += 1;
      if ((wrap.innerText || "").length > 520) break;
      n = n.nextElementSibling;
    }
    return {
      title: headingLabel(el),
      html: sanitizePeekHtml(wrap.innerHTML),
    };
  }

  function placePeek(anchor) {
    if (!peekEl || !anchor) return;
    peekEl.hidden = false;
    const r = anchor.getBoundingClientRect();
    const pw = peekEl.offsetWidth;
    const ph = peekEl.offsetHeight;
    const inRail = !!(navEl && navEl.contains(anchor));
    peekEl.classList.toggle("peek-rail", inRail);
    let top;
    let left;
    if (inRail) {
      const railBox = navEl.getBoundingClientRect();
      left = railBox.right + 12;
      top = r.top;
      if (left + pw > window.innerWidth - 12) {
        left = Math.max(railBox.right + 8, window.innerWidth - pw - 12);
      }
      if (top + ph > window.innerHeight - 12) top = window.innerHeight - ph - 12;
      if (top < 12) top = 12;
    } else {
      top = r.bottom + 10;
      left = r.left;
      if (top + ph > window.innerHeight - 12) top = r.top - ph - 10;
      if (left + pw > window.innerWidth - 12) left = window.innerWidth - pw - 12;
      if (left < 12) left = 12;
      if (top < 12) top = 12;
    }
    peekEl.style.top = Math.round(top) + "px";
    peekEl.style.left = Math.round(left) + "px";
  }

  function usablePeekImage(url) {
    if (!url) return "";
    if (/icon[-_.]|favicon|apple-touch|\/logo\b/i.test(url)) return "";
    return url;
  }

  function fillPeek(data) {
    peekEl.innerHTML = "";
    peekEl.className = "peek peek-" + (data.kind || "note");
    const image = usablePeekImage(data.image);
    if (image) {
      const img = document.createElement("img");
      img.className = "peek-media";
      img.src = image;
      img.alt = "";
      img.addEventListener("load", function () {
        if (peekAnchor) placePeek(peekAnchor);
      });
      peekEl.appendChild(img);
    }
    const k = document.createElement("p");
    k.className = "peek-kicker";
    k.textContent = data.kicker || "";
    peekEl.appendChild(k);
    if (data.title) {
      const t = document.createElement("p");
      t.className = "peek-title";
      t.textContent = data.title;
      peekEl.appendChild(t);
    }
    const body = document.createElement("div");
    body.className = "peek-body";
    if (data.html) body.innerHTML = data.html;
    else body.textContent = data.body || "";
    peekEl.appendChild(body);
  }

  function peekTarget(a) {
    if (!a) return null;
    const href = a.getAttribute("href") || "";
    if (!href || href.startsWith("javascript:") || href.startsWith("mailto:") || href.startsWith("tel:")) return null;
    if (a.dataset.path) return { kind: "local", path: a.dataset.path, hash: "" };
    if (a.classList.contains("link-local")) {
      try {
        const u = new URL(a.getAttribute("href"), location.href);
        return { kind: "local", path: u.searchParams.get("doc") || "", hash: (u.hash || "").replace(/^#/, "") };
      } catch (e) {
        return null;
      }
    }
    if (a.classList.contains("link-file")) {
      const path = (a.getAttribute("href") || "").replace(/^\//, "");
      return { kind: "file", path: path, file: fileKind(path) };
    }
    if (a.classList.contains("link-ext")) {
      return { kind: "ext", url: a.href, host: (a.querySelector(".ext-host") && a.querySelector(".ext-host").textContent) || "" };
    }
    if (href.charAt(0) === "#") return { kind: "hash", hash: href.slice(1) };
    return null;
  }

  async function fetchNoteText(path) {
    if (peekCache[path]) return peekCache[path];
    const res = await fetch("/" + encodePath(path), { cache: "no-store" });
    if (!res.ok) throw new Error("missing");
    const md = await res.text();
    peekCache[path] = md;
    return md;
  }

  async function showPeek(a) {
    if (!peekEl || !canHoverPeek() || lightbox.hidden === false) return;
    const info = peekTarget(a);
    if (!info) return;
    peekAnchor = a;
    const gen = ++peekGen;
    fillPeek({ kind: info.kind === "ext" ? "ext" : "note", kicker: "Loading", title: "", body: "…" });
    placePeek(a);
    try {
      if (info.kind === "hash" || (info.kind === "local" && info.path === currentPath && info.hash)) {
        const section = htmlFromSection(info.hash);
        if (section && gen === peekGen) {
          fillPeek({
            kind: "note",
            kicker: "On this page",
            title: section.title,
            html: section.html,
          });
          placePeek(a);
          return;
        }
      }
      if (info.kind === "local") {
        const md = await fetchNoteText(info.path);
        if (gen !== peekGen) return;
        const win = mdWindow(md, info.hash);
        const extracted = extractMath(win.md);
        const html = sanitizePeekHtml(restoreMath(marked.parse(extracted.md), extracted.slots));
        const meta = findNote(info.path);
        fillPeek({
          kind: "note",
          kicker: info.hash ? "Note · section" : "Note",
          title: win.title || (meta && meta.title) || info.path,
          html: html,
        });
        placePeek(a);
        return;
      }
      if (info.kind === "file") {
        if (info.file === "image") {
          fillPeek({
            kind: "file",
            kicker: extOf(info.path) || "image",
            title: info.path.split("/").pop(),
            image: "/" + encodePath(fullSrc(info.path)),
            body: "",
          });
        } else {
          fillPeek({
            kind: "file",
            kicker: "Local file",
            title: info.path.split("/").pop(),
            body: (extOf(info.path) || info.file) + " — click to open",
          });
        }
        placePeek(a);
        return;
      }
      if (info.kind === "ext") {
        const res = await fetch("/api/preview?url=" + encodeURIComponent(info.url), { cache: "no-store" });
        if (gen !== peekGen) return;
        const data = res.ok ? await res.json() : {};
        fillPeek({
          kind: "ext",
          kicker: data.host || info.host || "External",
          title: data.title || info.host || info.url,
          body: data.description || info.url,
          image: data.image || "",
        });
        placePeek(a);
      }
    } catch (err) {
      if (gen !== peekGen) return;
      fillPeek({ kind: "note", kicker: "Preview", title: "", body: "Could not load a preview." });
      placePeek(a);
    }
  }

  function schedulePeek(a) {
    if (!canHoverPeek() || !a) return;
    clearTimeout(peekHideTimer);
    if (peekAnchor === a && peekEl && !peekEl.hidden) return;
    clearTimeout(peekTimer);
    peekTimer = setTimeout(function () {
      showPeek(a);
    }, 280);
  }

  function bindPeekRoot(root) {
    if (!root) return;
    root.addEventListener("pointerover", function (ev) {
      const a = ev.target.closest("a[href]");
      if (!a || !root.contains(a)) return;
      schedulePeek(a);
    });
    root.addEventListener("pointerout", function (ev) {
      const a = ev.target.closest("a[href]");
      if (!a) return;
      const rel = ev.relatedTarget;
      if (rel && (a.contains(rel) || (peekEl && peekEl.contains(rel)))) return;
      scheduleHidePeek();
    });
  }

  function fullSrc(src) {
    return (src || "").replace("/thumbs/", "/");
  }

  function openLightbox(opts) {
    lbStage.innerHTML = "";
    const type = opts.type || "image";
    const src = fullSrc(opts.src);
    if (type === "video") {
      const v = document.createElement("video");
      v.src = src;
      v.controls = true;
      v.autoplay = true;
      v.addEventListener("click", function (ev) { ev.stopPropagation(); });
      lbStage.appendChild(v);
    } else if (type === "pdf") {
      const f = document.createElement("iframe");
      f.src = src;
      f.title = opts.alt || "PDF";
      f.addEventListener("click", function (ev) { ev.stopPropagation(); });
      lbStage.appendChild(f);
    } else {
      const img = document.createElement("img");
      img.src = src;
      img.alt = opts.alt || "";
      img.addEventListener("click", function (ev) { ev.stopPropagation(); });
      lbStage.appendChild(img);
    }
    lbCap.textContent = opts.alt || "";
    lightbox.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeLightbox() {
    lightbox.hidden = true;
    lbStage.innerHTML = "";
    document.body.style.overflow = "";
  }

  function enhanceMedia(root) {
    root.querySelectorAll("img[src]").forEach(function (img) {
      const src = img.getAttribute("src") || "";
      const kind = fileKind(src);
      if (kind === "video") {
        const v = document.createElement("video");
        v.src = src;
        v.controls = true;
        v.preload = "metadata";
        if (img.alt) v.setAttribute("aria-label", img.alt);
        img.replaceWith(v);
        v.addEventListener("click", function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          openLightbox({ type: "video", src: v.currentSrc || src, alt: img.alt || "" });
        });
        return;
      }
      if (kind === "audio") {
        const a = document.createElement("audio");
        a.src = src;
        a.controls = true;
        img.replaceWith(a);
        return;
      }
      if (kind === "pdf") {
        const f = document.createElement("iframe");
        f.src = src;
        f.className = "media-frame";
        f.title = img.alt || "PDF";
        img.replaceWith(f);
        f.addEventListener("click", function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          openLightbox({ type: "pdf", src: src, alt: img.alt || "" });
        });
        return;
      }
      img.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        openLightbox({ type: "image", src: img.currentSrc || src, alt: img.alt || "" });
      });
    });
    root.querySelectorAll("video").forEach(function (v) {
      v.controls = true;
      v.addEventListener("click", function (ev) {
        if (ev.target !== v) return;
      });
    });
    root.querySelectorAll("audio").forEach(function (a) {
      a.controls = true;
    });
  }

  function promoteMermaid(root) {
    root.querySelectorAll("pre code.language-mermaid").forEach(function (code) {
      const pre = code.parentElement;
      const div = document.createElement("div");
      div.className = "mermaid";
      div.textContent = code.textContent;
      if (pre) pre.replaceWith(div);
    });
  }

  function rewriteRelativeMedia(root, current) {
    const prefix = dirOf(current);
    if (!prefix) return;
    root.querySelectorAll("img[src], video[src], audio[src], source[src], iframe[src]").forEach(function (el) {
      const val = el.getAttribute("src");
      if (!val || /^(https?:|\/\/|data:|\/|blob:)/i.test(val)) return;
      el.setAttribute("src", prefix + val);
    });
  }

  function routeFromLocation() {
    const params = new URLSearchParams(location.search);
    const doc = params.get("doc") || defaultDoc;
    const hash = (location.hash || "").replace(/^#/, "");
    return { path: doc, hash: hash };
  }

  function setRoute(path, hash, replace) {
    const url = new URL(location.href);
    url.searchParams.set("doc", path);
    url.hash = hash || "";
    const fn = replace ? "replaceState" : "pushState";
    history[fn]({ path: path, hash: hash || "" }, "", url);
  }

  function findNote(path) {
    for (let i = 0; i < notes.length; i++) {
      if (notes[i].path === path) return notes[i];
    }
    return null;
  }

  function noteIndex(path) {
    for (let i = 0; i < notes.length; i++) {
      if (notes[i].path === path) return i;
    }
    return -1;
  }

  function neighbor(delta) {
    const i = noteIndex(currentPath);
    if (i < 0) return;
    const n = notes[i + delta];
    if (n) loadDoc(n.path, "", false);
  }

  function markActive(path) {
    navList.querySelectorAll(".nav-group-body a").forEach(function (a) {
      a.classList.toggle("active", a.dataset.path === path);
      if (a.dataset.path === path) {
        const sec = a.closest(".nav-group");
        if (sec && sec.classList.contains("is-collapsed")) setCollapsed(sec, false);
      }
    });
  }

  function scrollToHash(hash) {
    if (!hash) {
      window.scrollTo(0, 0);
      updateChrome();
      return;
    }
    const id = decodeURIComponent(hash);
    const el = document.getElementById(id);
    if (!el) {
      window.scrollTo(0, 0);
      updateChrome();
      return;
    }
    const header = document.querySelector(".top");
    const offset = header ? header.getBoundingClientRect().height + 12 : 64;
    const top = el.getBoundingClientRect().top + window.scrollY - offset;
    window.scrollTo(0, Math.max(0, top));
    updateChrome();
  }

  async function loadDoc(path, hash, replace) {
    currentPath = path;
    setRoute(path, hash, replace);
    markActive(path);
    const meta = findNote(path);
    crumb.textContent = meta ? meta.title : path;
    document.title = (meta ? meta.title : path) + " · " + folderTitle;
    hidePeek();
    article.innerHTML = "<p>Loading…</p>";
    try {
      const res = await fetch("/" + encodePath(path), { cache: "no-store" });
      if (!res.ok) throw new Error("Could not load " + path + " (" + res.status + ")");
      const md = await res.text();
      const extracted = extractMath(md);
      article.innerHTML = restoreMath(marked.parse(extracted.md), extracted.slots);
      rewriteRelativeMedia(article, path);
      slugHeadings(article);
      wrapTables(article);
      insertToc(article);
      addHeadingAnchors(article);
      decorateLinks(article, path);
      enhanceMedia(article);
      promoteMermaid(article);
      wrapCode(article);
      if (article.querySelector(".mermaid")) {
        try {
          await mermaid.run({ querySelector: "#doc .mermaid" });
        } catch (mmdErr) {
          console.warn("mermaid", mmdErr);
        }
      }
      if (typeof renderMathInElement === "function") {
        renderMathInElement(article, {
          delimiters: [
            { left: "\\[", right: "\\]", display: true },
            { left: "\\(", right: "\\)", display: false },
          ],
          throwOnError: false,
        });
      }
      requestAnimationFrame(function () {
        scrollToHash(hash);
      });
    } catch (err) {
      if (defaultDoc && path !== defaultDoc && findNote(defaultDoc)) {
        await loadDoc(defaultDoc, "", true);
        return;
      }
      article.innerHTML =
        '<div class="err"><p><strong>Could not load this note.</strong></p><p>' +
        String(err.message || err) +
        '</p><p>Use <a href="/">Folders</a> to pick a notes folder.</p></div>';
    }
  }

  function groupOrder() {
    const seen = [];
    notes.forEach(function (n) {
      const g = n.group || folderTitle;
      if (seen.indexOf(g) === -1) seen.push(g);
    });
    return seen;
  }

  function foldMap() {
    try {
      return JSON.parse(localStorage.getItem(FOLD_KEY) || "{}") || {};
    } catch (e) {
      return {};
    }
  }

  function groupIsCollapsed(name) {
    const m = foldMap()[folderKey] || {};
    return !!m[name];
  }

  function persistCollapsed(name, collapsed) {
    const all = foldMap();
    if (!all[folderKey]) all[folderKey] = {};
    if (collapsed) all[folderKey][name] = true;
    else delete all[folderKey][name];
    try {
      localStorage.setItem(FOLD_KEY, JSON.stringify(all));
    } catch (e) { /* ignore */ }
  }

  function syncFoldButton(sec) {
    const btn = sec.querySelector(".nav-fold");
    const g = sec.dataset.group || "";
    const collapsed = sec.classList.contains("is-collapsed");
    if (!btn) return;
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    btn.setAttribute("aria-label", (collapsed ? "Show " : "Hide ") + g);
    btn.title = collapsed ? "Show" : "Hide";
  }

  function setCollapsed(sec, collapsed) {
    sec.classList.toggle("is-collapsed", collapsed);
    persistCollapsed(sec.dataset.group, collapsed);
    syncFoldButton(sec);
    updateAllButton();
  }

  function updateAllButton() {
    if (!navAll) return;
    const groups = navList.querySelectorAll(".nav-group");
    navAll.hidden = groups.length === 0;
    let anyOpen = false;
    groups.forEach(function (sec) {
      if (!sec.classList.contains("is-collapsed")) anyOpen = true;
    });
    navAll.textContent = anyOpen ? "Hide all" : "Show all";
  }

  function applyFilter() {
    const query = ((filterInput && filterInput.value) || "").trim().toLowerCase();
    let shown = 0;
    navList.querySelectorAll(".nav-group").forEach(function (sec) {
      let visible = 0;
      sec.querySelectorAll(".nav-group-body a").forEach(function (a) {
        const hay = (a.textContent + " " + (a.dataset.path || "")).toLowerCase();
        const match = !query || hay.indexOf(query) !== -1;
        a.hidden = !match;
        if (match) visible += 1;
      });
      sec.hidden = visible === 0;
      if (query && visible) sec.classList.remove("is-collapsed");
      else if (!query) sec.classList.toggle("is-collapsed", groupIsCollapsed(sec.dataset.group));
      syncFoldButton(sec);
      shown += visible;
    });
    if (navEmpty) navEmpty.hidden = shown > 0;
    updateAllButton();
  }

  function renderNav() {
    const by = Object.create(null);
    notes.forEach(function (n) {
      const g = n.group || folderTitle;
      if (!by[g]) by[g] = [];
      by[g].push(n);
    });
    navList.innerHTML = "";
    groupOrder().forEach(function (g) {
      const items = by[g];
      if (!items || !items.length) return;
      const sec = document.createElement("section");
      sec.className = "nav-group";
      sec.dataset.group = g;
      const head = document.createElement("div");
      head.className = "nav-group-head";
      const fold = document.createElement("button");
      fold.type = "button";
      fold.className = "nav-fold";
      const chev = document.createElement("span");
      chev.className = "nav-chevron";
      chev.setAttribute("aria-hidden", "true");
      fold.appendChild(chev);
      fold.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        setCollapsed(sec, !sec.classList.contains("is-collapsed"));
      });
      const label = document.createElement("p");
      label.className = "nav-folder";
      label.textContent = g;
      head.appendChild(fold);
      head.appendChild(label);
      const body = document.createElement("div");
      body.className = "nav-group-body";
      items.forEach(function (n) {
        const a = document.createElement("a");
        a.href = "?doc=" + encodeURIComponent(n.path);
        a.dataset.path = n.path;
        a.textContent = shortTitle(n);
        a.addEventListener("click", function (ev) {
          if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0) return;
          ev.preventDefault();
          closeNav();
          loadDoc(n.path, "", false);
        });
        body.appendChild(a);
      });
      sec.appendChild(head);
      sec.appendChild(body);
      if (groupIsCollapsed(g)) sec.classList.add("is-collapsed");
      syncFoldButton(sec);
      navList.appendChild(sec);
    });
    applyFilter();
  }

  function shortTitle(n) {
    const t = n.title
      .replace(/^\d+\.\s*/, "")
      .replace(/\\\(([\s\S]*?)\\\)/g, "$1")
      .replace(/\\\[([\s\S]*?)\\\]/g, "$1");
    const name = n.path.split("/").pop();
    if (/^readme\.(md|markdown|mdown|mkd)$/i.test(name)) return "Overview";
    if (/^glossary\.(md|markdown|mdown|mkd)$/i.test(name)) return "Glossary";
    if (n.path.indexOf("/") !== -1) {
      let rest = n.path.replace(/\.(md|markdown|mdown|mkd)$/i, "");
      if (n.group && rest.indexOf(n.group + "/") === 0) {
        rest = rest.slice(n.group.length + 1);
      }
      return rest;
    }
    const m = name.match(/^(\d+)-/);
    if (m) return m[1] + " · " + t;
    return t;
  }

  function closeNav() {
    navEl.classList.remove("open");
    scrim.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
  }

  function openNav() {
    navEl.classList.add("open");
    scrim.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
  }

  function applyZen(on) {
    appEl.classList.toggle("zen", on);
    if (zenBtn) {
      zenBtn.setAttribute("aria-pressed", on ? "true" : "false");
      zenBtn.textContent = on ? "Notes" : "Wide";
      zenBtn.title = on ? "Show notes list" : "Hide notes list — more width";
    }
    try {
      localStorage.setItem(ZEN_KEY, on ? "1" : "0");
    } catch (e) { /* ignore */ }
  }

  function updateChrome() {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const p = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
    if (progressEl) progressEl.style.transform = "scaleX(" + p + ")";
    if (toTop) toTop.hidden = window.scrollY < 420;
  }

  function isTypingTarget(el) {
    if (!el) return false;
    const tag = (el.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return true;
    return !!el.isContentEditable;
  }

  toggle.addEventListener("click", function () {
    if (navEl.classList.contains("open")) closeNav();
    else openNav();
  });
  scrim.addEventListener("click", closeNav);

  if (zenBtn) {
    zenBtn.addEventListener("click", function () {
      applyZen(!appEl.classList.contains("zen"));
    });
  }
  if (filterInput) {
    filterInput.addEventListener("input", applyFilter);
  }
  if (navAll) {
    navAll.addEventListener("click", function () {
      const groups = navList.querySelectorAll(".nav-group");
      let anyOpen = false;
      groups.forEach(function (sec) {
        if (!sec.classList.contains("is-collapsed")) anyOpen = true;
      });
      const collapse = anyOpen;
      groups.forEach(function (sec) {
        sec.classList.toggle("is-collapsed", collapse);
        persistCollapsed(sec.dataset.group, collapse);
        syncFoldButton(sec);
      });
      updateAllButton();
    });
  }
  if (toTop) {
    toTop.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  document.getElementById("lb-close").addEventListener("click", function (ev) {
    ev.stopPropagation();
    closeLightbox();
  });
  lightbox.addEventListener("click", function (ev) {
    if (ev.target === lightbox || ev.target === lbCap || ev.target === lbStage) closeLightbox();
  });

  bindPeekRoot(article);
  bindPeekRoot(navList);
  if (navList) {
    navList.addEventListener("scroll", function () {
      if (!peekEl || peekEl.hidden) return;
      if (peekAnchor && peekAnchor.matches(":hover")) placePeek(peekAnchor);
      else hidePeek();
    }, { passive: true });
  }
  if (peekEl) {
    peekEl.addEventListener("pointerenter", function () {
      clearTimeout(peekHideTimer);
    });
    peekEl.addEventListener("pointerleave", scheduleHidePeek);
  }

  article.addEventListener("click", function (ev) {
    const a = ev.target.closest("a[href]");
    if (!a || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button !== 0) return;
    const href = a.getAttribute("href") || "";
    if (href.charAt(0) !== "#") return;
    const hash = href.slice(1);
    if (!hash) return;
    ev.preventDefault();
    setRoute(currentPath, hash, false);
    scrollToHash(hash);
  });

  document.addEventListener("keydown", function (ev) {
    const typing = isTypingTarget(ev.target);
    if (ev.key === "Escape") {
      if (peekEl && !peekEl.hidden) hidePeek();
      else if (!lightbox.hidden) closeLightbox();
      else closeNav();
      if (typing && filterInput) filterInput.blur();
      return;
    }
    if (typing) {
      if (ev.key === "Enter" && ev.target === filterInput) {
        const first = navList.querySelector("a:not([hidden])");
        if (first) {
          ev.preventDefault();
          closeNav();
          loadDoc(first.dataset.path, "", false);
        }
      }
      return;
    }
    if (ev.key === "/" && !ev.metaKey && !ev.ctrlKey) {
      ev.preventDefault();
      if (appEl.classList.contains("zen")) applyZen(false);
      openNav();
      if (filterInput) filterInput.focus();
      return;
    }
    if (ev.key === "[") {
      ev.preventDefault();
      neighbor(-1);
      return;
    }
    if (ev.key === "]") {
      ev.preventDefault();
      neighbor(1);
      return;
    }
    if (ev.key === "w" || ev.key === "W") {
      applyZen(!appEl.classList.contains("zen"));
    }
  });

  window.addEventListener("scroll", updateChrome, { passive: true });
  window.addEventListener("resize", function () {
    updateChrome();
    if (peekEl && !peekEl.hidden && peekAnchor) placePeek(peekAnchor);
  });
  window.addEventListener("scroll", function () {
    if (!peekEl || peekEl.hidden) return;
    if (peekAnchor && peekAnchor.matches(":hover")) {
      placePeek(peekAnchor);
      return;
    }
    hidePeek();
  }, { passive: true });

  function typeStep() {
    return Number(article.getAttribute("data-type") || "1");
  }
  function setType(n) {
    const v = Math.max(0, Math.min(TYPE_MAX, n));
    article.setAttribute("data-type", String(v));
    try {
      localStorage.setItem(TYPE_KEY, String(v));
    } catch (e) { /* ignore */ }
  }
  document.getElementById("type-up").addEventListener("click", function () {
    setType(typeStep() + 1);
  });
  document.getElementById("type-down").addEventListener("click", function () {
    setType(typeStep() - 1);
  });
  try {
    const saved = localStorage.getItem(TYPE_KEY);
    if (saved !== null) setType(Number(saved));
  } catch (e) { /* ignore */ }
  try {
    if (localStorage.getItem(ZEN_KEY) === "1") applyZen(true);
  } catch (e) { /* ignore */ }

  window.addEventListener("popstate", function () {
    const r = routeFromLocation();
    loadDoc(r.path, r.hash, true);
  });

  async function boot() {
    try {
      const st = await fetch("/api/state", { cache: "no-store" });
      if (st.ok) {
        const state = await st.json();
        if (state && state.gutter) {
          document.documentElement.style.setProperty("--gutter", state.gutter);
        }
        const verEl = document.getElementById("app-version");
        if (verEl && state && state.version) {
          verEl.hidden = false;
          verEl.textContent = "v" + state.version;
        }
        if (!state.open) {
          location.replace("/");
          return;
        }
      }
      const res = await fetch("/api/notes", { cache: "no-store" });
      if (res.status === 409) {
        location.replace("/");
        return;
      }
      if (!res.ok) throw new Error("notes list failed");
      const data = await res.json();
      notes = data.notes || [];
      folderTitle = data.title || "Markdown";
      folderKey = data.path || folderTitle;
      defaultDoc = data.defaultDoc || (notes[0] && notes[0].path) || "";
      if (brandName) brandName.textContent = folderTitle;
      else brand.textContent = folderTitle;
      brand.setAttribute("href", "?doc=" + encodeURIComponent(defaultDoc));
      brand.addEventListener("click", function (ev) {
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0) return;
        ev.preventDefault();
        closeNav();
        loadDoc(defaultDoc, "", false);
      });
      renderNav();
    } catch (err) {
      article.innerHTML =
        '<div class="err"><p><strong>This page needs the local server.</strong></p>' +
        "<p>Run <code>python3 serve.py</code> and open <code>http://127.0.0.1:8765</code> to pick a folder.</p></div>";
      return;
    }
    const r = routeFromLocation();
    const path = findNote(r.path) ? r.path : defaultDoc;
    if (!path) {
      article.innerHTML =
        '<div class="err"><p><strong>No markdown in this folder.</strong></p>' +
        '<p>Use <a href="/">Folders</a> to pick another.</p></div>';
      return;
    }
    await loadDoc(path, path === r.path ? r.hash : "", true);
  }

  boot();
})();
