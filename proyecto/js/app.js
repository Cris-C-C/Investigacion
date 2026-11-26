import { inlineTokens, parseTable, plainText, scanMetadata, tableToCSV } from "./latex-parser.js";
import { parseBib, referenceLinks, shortAuthor } from "./bib-parser.js";

const byId = (id) => document.getElementById(id);
const bibliography = new Map();
const filter = { text: byId("search"), label: byId("label-filter"), cite: byId("cite-filter") };
const list = byId("table-list");
const view = byId("table-view");
const status = byId("load-status");
const dialog = byId("reference-dialog");
let tables = [];
let activePath = "";
let focusTable = false;
let feedbackTimer;
let dialogOpener;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function button(text, handler, className) {
  const element = node("button", text, className);
  element.type = "button";
  element.addEventListener("click", handler);
  return element;
}

function anchor(text, href, className) {
  const element = node("a", text, className);
  element.href = href;
  return element;
}

function inform(message) {
  const feedback = byId("feedback");
  clearTimeout(feedbackTimer);
  feedback.textContent = message;
  feedback.hidden = false;
  feedbackTimer = setTimeout(() => { feedback.hidden = true; }, 4500);
}

async function copyText(text, success) {
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Portapapeles no disponible.");
    await navigator.clipboard.writeText(text);
    inform(success);
  } catch {
    const field = node("textarea");
    field.value = text;
    field.style.cssText = "position:fixed;left:-9999px;top:0";
    const previous = document.activeElement;
    document.body.append(field);
    field.select();
    let copied = false;
    try { copied = document.execCommand("copy"); } catch { /* The browser may deny clipboard access. */ }
    field.remove();
    previous?.focus();
    inform(copied ? success : "El navegador bloqueó el acceso al portapapeles.");
  }
}

const media = window.matchMedia("(prefers-color-scheme: dark)");
let chosenTheme;
try { chosenTheme = localStorage.getItem("atlas-theme"); } catch { /* Storage is optional. */ }
function applyTheme() {
  const dark = (chosenTheme ?? (media.matches ? "dark" : "light")) === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  byId("theme").setAttribute("aria-pressed", String(dark));
  byId("theme-symbol").textContent = dark ? "☀" : "☾";
  byId("theme-text").textContent = dark ? "Tema claro" : "Tema oscuro";
}
applyTheme();
media.addEventListener("change", applyTheme);
byId("theme").addEventListener("click", () => {
  chosenTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  try { localStorage.setItem("atlas-theme", chosenTheme); } catch { /* Keep the session preference. */ }
  applyTheme();
});

function formatBib(text) {
  try { return plainText(inlineTokens(text)); } catch { return text; }
}

function citeLabel(key, command) {
  const entry = bibliography.get(key);
  if (!entry) return key;
  const author = shortAuthor(entry.fields.author, formatBib);
  const year = entry.fields.year ? formatBib(entry.fields.year) : "s. f.";
  if (command === "citeauthor") return author;
  if (command === "citeyear") return year;
  if (command === "citep") return author + ", " + year;
  return author + " (" + year + ")";
}

function citeParts(token) {
  const [first, second] = token.notes;
  const parenthetical = token.command === "citep";
  return {
    start: (parenthetical ? "(" : "") + (second === undefined ? "" : formatBib(first) + " "),
    end: (first === undefined ? "" : ", " + formatBib(second ?? first)) + (parenthetical ? ")" : ""),
  };
}

function citePlain(token) {
  const { start, end } = citeParts(token);
  return start + token.keys.map((key) => citeLabel(key, token.command)).join("; ") + end;
}

function referenceId(key) { return "ref-" + encodeURIComponent(key); }
function tableHash(path) { return "#tabla=" + encodeURIComponent(path); }

function referenceAnchor(key, text) {
  const link = anchor(text, "#" + encodeURIComponent(referenceId(key)), "cite");
  link.dataset.citeKey = key;
  link.setAttribute("aria-haspopup", "dialog");
  link.addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    openReference(key, link);
  });
  return link;
}

function openReference(key, opener) {
  const entry = bibliography.get(key);
  const names = {
    author: "Autores", title: "Título", journal: "Revista", journaltitle: "Revista",
    year: "Año", volume: "Volumen", number: "Número", pages: "Páginas",
    booktitle: "Libro", publisher: "Editorial", date: "Fecha", note: "Nota",
  };
  byId("reference-key").textContent = key;
  byId("reference-title").textContent = entry.fields.title ? formatBib(entry.fields.title) : key;
  const fields = byId("reference-fields");
  fields.replaceChildren();
  const ordered = [...new Set([...Object.keys(names), ...Object.keys(entry.fields)])];
  for (const field of ordered) {
    const value = entry.fields[field];
    if (!value) continue;
    fields.append(node("dt", Object.hasOwn(names, field) ? names[field] : field),
      node("dd", field === "author" ? formatBib(value).replace(/ and /g, "; ") : formatBib(value)));
  }
  const links = byId("reference-links");
  links.replaceChildren();
  for (const { url, label } of referenceLinks(entry.fields)) {
    const link = anchor(label, url, "button");
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    links.append(link);
  }
  byId("reference-code").textContent = entry.raw;
  byId("reference-raw").open = false;
  dialogOpener = opener;
  dialog.showModal();
}

dialog.addEventListener("close", () => dialogOpener?.focus());
dialog.addEventListener("click", (event) => {
  if (event.target !== dialog) return;
  const box = dialog.getBoundingClientRect();
  if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
});

function renderInline(container, tokens) {
  for (const token of tokens) {
    if (token.type === "text") container.append(token.value);
    if (token.type === "break") container.append(node("br"));
    if (token.type === "group") renderInline(container, token.children);
    if (token.type === "style") {
      const element = node(token.tag);
      renderInline(element, token.children);
      container.append(element);
    }
    if (token.type === "math") {
      const math = node("span");
      if (window.katex) window.katex.render(token.value, math, { throwOnError: false, trust: false, strict: "ignore" });
      else {
        math.className = "math-fallback";
        math.textContent = "$" + token.value + "$";
        math.title = "KaTeX no está disponible";
      }
      container.append(math);
    }
    if (token.type === "ref") {
      const target = tables.find((table) => table.labels.includes(token.value));
      container.append(target ? anchor(token.value, tableHash(target.path)) : node("span", token.value, "missing-cite"));
    }
    if (token.type === "cite") {
      const { start, end } = citeParts(token);
      container.append(start);
      token.keys.forEach((key, i) => {
        if (i) container.append("; ");
        if (bibliography.has(key)) container.append(referenceAnchor(key, citeLabel(key, token.command)));
        else {
          const element = node("span", key + " (sin referencia)", "missing-cite");
          element.title = "Clave ausente en la bibliografía";
          element.dataset.missingKey = key;
          container.append(element);
        }
      });
      container.append(end);
    }
  }
}

function cssWidth(latex) {
  if (!latex) return "";
  const fixed = /^(\d*\.?\d+)\s*(px|pt|mm|cm|in|em|ex)$/.exec(latex);
  if (fixed) return fixed[1] + fixed[2];
  const fraction = /^(\d*\.?\d+)?\s*\\(?:textwidth|linewidth|columnwidth)$/.exec(latex);
  return fraction ? Math.max(0, Number(fraction[1] ?? 1) * 100) + "%" : "";
}

function renderTable(model, captionId) {
  const scroll = node("div", undefined, "table-scroll");
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", "Tabla con desplazamiento horizontal");
  const table = node("table", undefined, "data-table");
  table.setAttribute("aria-labelledby", captionId);
  const cols = node("colgroup");
  for (const spec of model.columns) {
    const col = node("col");
    col.style.width = cssWidth(spec.width);
    cols.append(col);
  }
  table.append(cols);
  const body = node("tbody");
  for (const [i, row] of model.rows.entries()) {
    const tr = node("tr");
    for (const rule of row.before) tr.classList.add("rule-" + rule);
    for (const rule of row.after) tr.classList.add("after-" + rule);
    for (const cell of row.cells) {
      const header = i < model.headerCount;
      const td = node(header ? "th" : "td", undefined, "align-" + cell.align);
      if (header && cell.colSpan === 1) td.scope = "col";
      if (cell.colSpan > 1) td.colSpan = cell.colSpan;
      if (cell.rowSpan > 1) td.rowSpan = cell.rowSpan;
      if (cell.left) td.classList.add("edge-left");
      if (cell.right) td.classList.add("edge-right");
      if (cell.width) td.style.width = cssWidth(cell.width);
      renderInline(td, cell.tokens);
      tr.append(td);
    }
    body.append(tr);
  }
  table.append(body);
  scroll.append(table);
  return scroll;
}

function renderReferences(record) {
  const section = node("section", undefined, "references");
  section.append(node("h2", "Referencias"));
  if (!record.citations.length) {
    section.append(node("p", "Esta tabla no contiene citas.", "muted"));
    return section;
  }
  const refs = node("ol");
  for (const key of record.citations) {
    const item = node("li");
    item.id = referenceId(key);
    const entry = bibliography.get(key);
    if (entry) {
      item.append(referenceAnchor(key, citeLabel(key, "cite")));
      if (entry.fields.title) item.append(" · " + formatBib(entry.fields.title));
    } else item.append(node("span", key + " (sin referencia)", "missing-cite"));
    refs.append(item);
  }
  section.append(refs);
  return section;
}

function renderRecord(record) {
  view.replaceChildren();
  if (!record) return;
  const article = node("article", undefined, "sheet");
  article.dataset.tablePath = record.path;
  article.append(node("p", record.labels.join(" · ") || record.path.split("/").at(-1), "sheet-meta"));
  const heading = node("h1");
  heading.id = "table-title";
  heading.tabIndex = -1;
  try {
    if (record.caption) renderInline(heading, inlineTokens(record.caption));
    else heading.textContent = record.title;
  } catch { heading.textContent = record.title; }
  article.append(heading);

  const actions = node("div", undefined, "actions");
  const copy = button("Copiar LaTeX", () => copyText(record.source, "Código LaTeX copiado."), "primary");
  const download = anchor("Descargar .tex", assetUrl(record.path, "tablas"), "button");
  download.download = record.path.split("/").at(-1);
  const csv = button("Copiar CSV", () => copyText(record.csv, "Tabla CSV copiada."));
  copy.disabled = record.source === undefined;
  csv.disabled = !record.model;
  actions.append(copy, download, csv);
  article.append(actions);

  const missing = record.citations.filter((key) => !bibliography.has(key));
  if (missing.length) article.append(node("p", "Claves sin bibliografía: " + missing.join(", "), "notice error"));
  if (record.model) {
    try { article.append(renderTable(record.model, heading.id)); }
    catch (error) {
      record.error = error.message;
      csv.disabled = true;
    }
  }
  if (record.error) {
    article.append(node("p", "No se pudo interpretar la tabla. " + record.error, "notice error"));
    if (record.source !== undefined) {
      const raw = node("pre");
      raw.append(node("code", record.source));
      article.append(raw);
    }
  }
  article.append(renderReferences(record));
  view.append(article);
  if (focusTable) {
    heading.focus();
    focusTable = false;
  }
}

function normalize(text) {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLocaleLowerCase("es");
}

function hashPath() {
  if (!location.hash.startsWith("#tabla=")) return "";
  try { return decodeURIComponent(location.hash.slice(7)); } catch { return ""; }
}

function updateResults() {
  const query = normalize(filter.text.value).trim().split(/\s+/).filter(Boolean);
  const label = filter.label.value;
  const cite = filter.cite.value;
  const results = tables.filter((record) =>
    query.every((word) => record.search.includes(word)) &&
    (!label || record.labels.includes(label)) &&
    (!cite || record.citations.includes(cite)));
  const requested = hashPath();
  const current = results.find((record) => record.path === requested) ??
    results.find((record) => record.path === activePath) ?? results[0];
  byId("result-count").textContent = results.length + (results.length === 1 ? " tabla" : " tablas");
  byId("clear-filters").hidden = !(query.length || label || cite);
  list.replaceChildren();
  for (const record of results) {
    const link = anchor(record.title, tableHash(record.path), "table-link");
    if (record.labels.length) link.append(node("small", record.labels.join(" · ")));
    if (record === current) link.setAttribute("aria-current", "page");
    link.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      focusTable = true;
      if (location.hash === link.hash) {
        event.preventDefault();
        renderRecord(record);
      } else {
        event.preventDefault();
        history.pushState(null, "", link.hash);
        updateResults();
      }
    });
    list.append(link);
  }
  status.hidden = !!current;
  if (!current) status.textContent = tables.length ? "Ninguna tabla coincide con los filtros." : "El repositorio todavía no tiene tablas.";
  if ((current?.path ?? "") !== activePath || focusTable) {
    activePath = current?.path ?? "";
    renderRecord(current);
  }
}

window.addEventListener("hashchange", () => {
  const path = hashPath();
  if (path && tables.some((table) => table.path === path)) {
    filter.text.value = "";
    filter.label.value = "";
    filter.cite.value = "";
    focusTable = true;
  }
  updateResults();
});
filter.text.addEventListener("input", updateResults);
filter.label.addEventListener("change", updateResults);
filter.cite.addEventListener("change", updateResults);
byId("clear-filters").addEventListener("click", () => {
  for (const input of Object.values(filter)) input.value = "";
  filter.text.focus();
  updateResults();
});

function setOptions(element, values) {
  const unique = [...new Set(values)].filter(Boolean).sort((a, b) => a.localeCompare(b, "es"));
  for (const value of unique) {
    const option = node("option", value);
    option.value = value;
    element.append(option);
  }
}

function assetUrl(path, directory) {
  const root = "data/" + directory + "/";
  if (typeof path !== "string" || !path.startsWith(root) || path.includes("\\") ||
      path.split("/").some((part) => !part || part === "." || part === "..")) {
    throw new Error("Ruta inválida en manifest.json.");
  }
  return path.split("/").map(encodeURIComponent).join("/");
}

async function tableRecord(meta) {
  const record = { path: meta.path, labels: meta.labels ?? [], citations: meta.citations ?? [],
    caption: "", title: meta.path.split("/").at(-1).replace(/\.tex$/i, "") };
  try {
    const response = await fetch(assetUrl(meta.path, "tablas"));
    if (!response.ok) throw new Error("HTTP " + response.status + " al cargar " + meta.path + ".");
    record.source = new TextDecoder("utf-8", { fatal: true }).decode(await response.arrayBuffer());
    try {
      const meta = scanMetadata(record.source);
      record.caption = meta.caption;
      record.labels = meta.labels;
      record.citations = meta.citations;
      record.title = formatBib(meta.caption).trim() || record.title;
    } catch (error) { record.error = error.message; }
    record.model = parseTable(record.source);
    record.csv = tableToCSV(record.model, (tokens) => plainText(tokens, citePlain));
  } catch (error) {
    record.model = null;
    record.error = error.message;
  }
  record.search = normalize([record.title, record.path, record.source ?? "", ...record.labels, ...record.citations,
    ...(record.model?.rows.flatMap((row) => row.cells.map((cell) => plainText(cell.tokens, citePlain))) ?? []),
  ].join(" "));
  return record;
}

async function start() {
  try {
    const response = await fetch("data/manifest.json");
    if (!response.ok) throw new Error("HTTP " + response.status + " al cargar data/manifest.json.");
    const manifest = await response.json();
    if (manifest.version !== 1 || !Array.isArray(manifest.tables) || !Array.isArray(manifest.bibliography)) {
      throw new Error("Formato de manifest.json inválido.");
    }
    for (const table of manifest.tables) assetUrl(table.path, "tablas");
    const bibs = await Promise.allSettled(manifest.bibliography.map(async (path) => {
      const res = await fetch(assetUrl(path, "bib"));
      if (!res.ok) throw new Error("HTTP " + res.status);
      return parseBib(new TextDecoder("utf-8", { fatal: true }).decode(await res.arrayBuffer()));
    }));
    const warnings = byId("library-warnings");
    bibs.forEach((result, i) => {
      const path = manifest.bibliography[i];
      const warn = (message) => warnings.append(node("p", path + " · " + message, "notice error"));
      if (result.status === "rejected") {
        warn(result.reason.message);
        return;
      }
      for (const error of result.value.errors) warn(error);
      for (const entry of result.value.entries) {
        if (bibliography.has(entry.key)) warn("Clave duplicada: " + entry.key + ".");
        else bibliography.set(entry.key, entry);
      }
    });
    tables = await Promise.all(manifest.tables.map(tableRecord));
    setOptions(filter.label, tables.flatMap((record) => record.labels));
    setOptions(filter.cite, tables.flatMap((record) => record.citations));
    updateResults();
  } catch (error) {
    status.hidden = false;
    status.classList.add("error");
    status.textContent = "No se pudo cargar el repositorio. " + error.message + " Sirve proyecto/ por HTTP y verifica el manifiesto.";
  }
}

start();
