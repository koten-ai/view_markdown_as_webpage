/* global marked, mermaid, renderMathInElement */
(function () {
  "use strict";

  const article = document.getElementById("doc");
  const navEl = document.getElementById("nav");
  const navList = document.getElementById("nav-list");
  const crumb = document.getElementById("crumb");
  const brand = document.getElementById("brand");
  const brandName = brand.querySelector(".logo-name");
  const toggle = document.getElementById("nav-toggle");
  const scrim = document.getElementById("scrim");
  const lightbox = document.getElementById("lightbox");
  const lbStage = document.getElementById("lb-stage");
  const lbCap = document.getElementById("lb-cap");
  const TYPE_MAX = 3;
  const TYPE_KEY = "mdview-type";

  const MD_RE = /\.(md|markdown|mdown|mkd)(?:$|[?#])/i;
  const IMAGE_RE = /\.(png|jpe?g|gif|webp|avif|svg|bmp|ico|tiff?|heic|heif)(?:$|[?#])/i;
  const VIDEO_RE = /\.(mp4|webm|ogv|mov|m4v)(?:$|[?#])/i;
  const AUDIO_RE = /\.(mp3|wav|ogg|m4a|flac|aac)(?:$|[?#])/i;
  const PDF_RE = /\.pdf(?:$|[?#])/i;
  const TEXT_RE = /\.(txt|csv|tsv|json|ya?ml|xml|log|rst|adoc|html?|css|js|ts)(?:$|[?#])/i;

  let notes = [];
  let folderTitle = "Markdown";
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

  function slugHeadings(root) {
    const seen = Object.create(null);
    root.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach(function (h) {
      if (h.id) return;
      let slug = githubSlug(h.textContent || "section");
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

  function wrapTables(root) {
    root.querySelectorAll("table").forEach(function (table) {
      if (table.parentElement && table.parentElement.classList.contains("table-wrap")) return;
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
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

  function markActive(path) {
    navList.querySelectorAll("a").forEach(function (a) {
      a.classList.toggle("active", a.dataset.path === path);
    });
  }

  function scrollToHash(hash) {
    if (!hash) {
      window.scrollTo(0, 0);
      return;
    }
    const id = decodeURIComponent(hash);
    const el = document.getElementById(id);
    if (!el) {
      window.scrollTo(0, 0);
      return;
    }
    const header = document.querySelector(".top");
    const offset = header ? header.getBoundingClientRect().height + 12 : 64;
    const top = el.getBoundingClientRect().top + window.scrollY - offset;
    window.scrollTo(0, Math.max(0, top));
  }

  async function loadDoc(path, hash, replace) {
    currentPath = path;
    setRoute(path, hash, replace);
    markActive(path);
    const meta = findNote(path);
    crumb.textContent = meta ? meta.title : path;
    document.title = (meta ? meta.title : path) + " · " + folderTitle;
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
      decorateLinks(article, path);
      enhanceMedia(article);
      promoteMermaid(article);
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
      article.innerHTML =
        '<div class="err"><p><strong>Could not load this note.</strong></p><p>' +
        String(err.message || err) +
        "</p><p>Run <code>python3 serve.py /path/to/notes</code> and open <code>http://127.0.0.1:8765</code>.</p></div>";
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
      const h = document.createElement("p");
      h.className = "nav-kicker";
      h.textContent = g;
      sec.appendChild(h);
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
        sec.appendChild(a);
      });
      navList.appendChild(sec);
    });
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

  toggle.addEventListener("click", function () {
    if (navEl.classList.contains("open")) closeNav();
    else openNav();
  });
  scrim.addEventListener("click", closeNav);

  document.getElementById("lb-close").addEventListener("click", function (ev) {
    ev.stopPropagation();
    closeLightbox();
  });
  lightbox.addEventListener("click", function (ev) {
    if (ev.target === lightbox || ev.target === lbCap || ev.target === lbStage) closeLightbox();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") {
      if (!lightbox.hidden) closeLightbox();
      else closeNav();
    }
  });

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

  window.addEventListener("popstate", function () {
    const r = routeFromLocation();
    loadDoc(r.path, r.hash, true);
  });

  async function boot() {
    try {
      const res = await fetch("/api/notes", { cache: "no-store" });
      if (!res.ok) throw new Error("notes list failed");
      const data = await res.json();
      notes = data.notes || [];
      folderTitle = data.title || "Markdown";
      defaultDoc = data.defaultDoc || (notes[0] && notes[0].path) || "README.md";
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
        "<p>From this repo, or with a path to another folder:</p>" +
        "<pre><code>python3 serve.py /path/to/notes</code></pre>" +
        "<p>Then open <code>http://127.0.0.1:8765</code> so it can read the markdown and files.</p></div>";
      return;
    }
    const r = routeFromLocation();
    await loadDoc(r.path, r.hash, true);
  }

  boot();
})();
