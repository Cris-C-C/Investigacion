const months = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

export function parseBib(source) {
  const text = source.replace(/^\uFEFF/, "");
  const macros = new Map(months.map((month) => [month.slice(0, 3).toLowerCase(), month]));
  const entries = [], errors = [];
  let pos = 0;
  const line = (at) => text.slice(0, at).split("\n").length;
  const fail = (message) => { throw new Error("Línea " + line(pos) + ": " + message); };

  function skip() {
    while (pos < text.length) {
      if (/\s/.test(text[pos])) pos++;
      else if (text[pos] === "%") {
        const newline = text.indexOf("\n", pos);
        pos = newline === -1 ? text.length : newline + 1;
      } else break;
    }
  }

  function take(pattern) {
    const value = pattern.exec(text.slice(pos))?.[0];
    if (value) pos += value.length;
    return value;
  }

  function expect(ch) {
    skip();
    if (text[pos] !== ch) fail("Se esperaba " + ch + ".");
    pos++;
  }

  function delimited(closing, opening) {
    const start = pos;
    let depth = 0;
    let braces = 0;
    while (pos < text.length) {
      const ch = text[pos++];
      if (ch === "\\") {
        pos++;
        continue;
      }
      if (opening !== "{" && opening !== '"') {
        if (ch === "{") braces++;
        if (ch === "}") braces--;
      }
      if (!braces && !depth && ch === closing) return text.slice(start, pos - 1);
      if (!braces && ch === (opening === '"' ? "{" : opening)) depth++;
      if (!braces && ch === (opening === '"' ? "}" : closing)) depth--;
      if (depth < 0 || braces < 0) fail("Llave inesperada en un valor.");
    }
    fail("Valor o entrada sin cierre.");
  }

  function value() {
    const parts = [];
    do {
      skip();
      const opening = text[pos];
      if (opening === "{" || opening === '"') {
        pos++;
        parts.push(delimited(opening === "{" ? "}" : '"', opening));
      } else {
        const bare = take(/^[\w.:+\/-]+/);
        if (!bare) fail("Valor BibTeX inválido.");
        parts.push(macros.get(bare.toLowerCase()) ?? bare);
      }
      skip();
    } while (text[pos] === "#" && ++pos);
    return parts.join("");
  }

  while (pos < text.length) {
    skip();
    if (text[pos] !== "@") {
      const next = /^[^@%\r\n]+/.exec(text.slice(pos))?.[0];
      pos += next?.length ?? 1;
      continue;
    }
    const start = pos++;
    try {
      const type = take(/^[a-zA-Z]+\b/)?.toLowerCase();
      if (!type) fail("Tipo de entrada inválido.");
      skip();
      const opening = text[pos++];
      if (opening !== "{" && opening !== "(") fail("Se esperaba { o (.");
      const closing = opening === "{" ? "}" : ")";
      if (type === "comment") {
        delimited(closing, opening);
        continue;
      }
      if (type === "preamble") {
        value();
        expect(closing);
        continue;
      }
      skip();
      if (type === "string") {
        const name = take(/^[a-zA-Z][\w.:-]*/);
        if (!name) fail("Nombre de macro inválido.");
        expect("=");
        const expanded = value();
        if (text[pos] === ",") pos++;
        expect(closing);
        macros.set(name.toLowerCase(), expanded);
        continue;
      }

      const key = take(/^[^\s,=(){}"%#@]+/);
      if (!key) fail("Clave bibliográfica vacía o inválida.");
      skip();
      if (text[pos] !== closing) expect(",");
      const fields = Object.create(null);
      skip();
      while (text[pos] !== closing) {
        const name = take(/^[a-zA-Z][\w-]*/)?.toLowerCase();
        if (!name) fail("Nombre de campo inválido o entrada sin cierre.");
        expect("=");
        const expanded = value();
        if (Object.hasOwn(fields, name)) errors.push("Línea " + line(pos) + ": Campo " + name + " repetido en " + key + ".");
        else fields[name] = expanded;
        if (text[pos] !== closing) expect(",");
        skip();
      }
      pos++;
      entries.push({ key, type, fields, raw: text.slice(start, pos), line: line(start) });
    } catch (error) {
      errors.push(error.message);
      // Resume with the next entry starting on its own line.
      const next = /\n[ \t]*(@[a-zA-Z]+\s*[{(])/.exec(text.slice(start + 1));
      pos = next ? start + 1 + next.index + next[0].indexOf("@") : text.length;
    }
  }
  return { entries, errors };
}

function splitTopLevel(text, delimiter) {
  const parts = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === "\\") {
      i++;
      continue;
    }
    if (text[i] === "{") depth++;
    if (text[i] === "}") depth--;
    if (depth) continue;
    const match = delimiter.exec(text.slice(i));
    if (!match) continue;
    parts.push(text.slice(start, i).trim());
    i += match[0].length - 1;
    start = i + 1;
  }
  parts.push(text.slice(start).trim());
  return parts.filter(Boolean);
}

function familyName(author) {
  if (/^\{[^{}]*\}$/.test(author)) return author;
  const names = splitTopLevel(author, /^,/);
  if (names.length > 1) return names[0];
  const words = splitTopLevel(author, /^\s+/);
  let first = words.length - 1;
  while (first > 0 && /^\p{Ll}/u.test(words[first - 1])) first--;
  return words.slice(first).join(" ");
}

export function shortAuthor(value = "", decode = (text) => text.replace(/[{}]/g, "")) {
  const names = splitTopLevel(value, /^\s+and\s+/i);
  if (!names.length) return "Autor desconocido";
  const first = decode(familyName(names[0]));
  if (names.length === 1) return first;
  if (names.length > 2 || names[1].toLowerCase() === "others") return first + " et al.";
  return first + " y " + decode(familyName(names[1]));
}

function webUrl(value) {
  try {
    const url = new URL(value.trim());
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

export function referenceLinks(fields) {
  const output = new Map();
  const add = (name, value) => {
    const url = value && webUrl(value);
    if (url && !output.has(url)) output.set(url, name);
  };
  const doi = fields.doi?.trim().replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i, "");
  if (doi) add("DOI", "https://doi.org/" + doi.split("/").map(encodeURIComponent).join("/"));
  const eprint = fields.eprint?.trim();
  const arxiv = fields.arxiv?.trim() || fields.arxivid?.trim() ||
    (eprint && (/arxiv/i.test(fields.archiveprefix ?? fields.eprinttype ?? "") ||
      /^(?:\d{4}\.\d{4,5}|[a-z.-]+\/\d{7})(?:v\d+)?$/i.test(eprint)) ? eprint : "");
  if (arxiv) {
    const id = arxiv.replace(/^arxiv:\s*/i, "");
    add("arXiv", webUrl(id) || "https://arxiv.org/abs/" + id.split("/").map(encodeURIComponent).join("/"));
  }
  const ads = fields.adsurl || fields.ads || fields.bibcode;
  if (ads) add("ADS", webUrl(ads) || "https://ui.adsabs.harvard.edu/abs/" + encodeURIComponent(ads.trim()) + "/abstract");
  const url = fields.url && webUrl(fields.url);
  if (url) {
    const host = new URL(url).hostname;
    const label = /(^|\.)adsabs\.harvard\.edu$/.test(host) ? "ADS" : /(^|\.)arxiv\.org$/.test(host) ? "arXiv" : "URL";
    add(label, url);
  }
  return Array.from(output, ([url, label]) => ({ url, label }));
}
