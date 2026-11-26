// Return a table model so the app can render source values with DOM nodes.
const citeCommands = new Set(["cite", "citep", "citet", "citeauthor", "citeyear"]);
const tableEnvs = new Set(["tabular", "tabular*", "longtable"]);
const sections = new Set(["endfirsthead", "endhead", "endfoot", "endlastfoot"]);

export class LatexError extends Error {
  constructor(source, index, message) {
    const line = source.slice(0, index).split("\n").length;
    super("Línea " + line + ": " + message);
    this.line = line;
    this.position = index;
    this.reason = message;
  }
}

function commandAt(text, i) {
  const name = /^[a-zA-Z]+|^[\s\S]/.exec(text.slice(i + 1))?.[0] ?? "";
  return { name, end: i + 1 + name.length };
}

export function stripComments(text) {
  return text.replace(/\\[\s\S]|%[^\n\r]*/g, (token) =>
    token.startsWith("\\") ? token : " ".repeat(token.length));
}

function arg(text, start, opening = "{", required = true) {
  let i = start;
  while (i < text.length && /\s/.test(text[i])) i++;
  if (text[i] !== opening) {
    if (required) throw new LatexError(text, i, "Se esperaba " + opening + ".");
    return null;
  }
  const closing = { "{": "}", "[": "]", "(": ")" }[opening];
  const content = ++i;
  let depth = 1;
  let braces = 0;
  while (i < text.length) {
    const ch = text[i];
    if (ch === "\\") {
      i = commandAt(text, i).end;
      continue;
    }
    if (opening !== "{") {
      if (ch === "{") braces++;
      if (ch === "}") braces--;
    }
    if (!braces && ch === opening) depth++;
    if (!braces && ch === closing && --depth === 0) {
      return { value: text.slice(content, i), start: content, end: i + 1 };
    }
    i++;
  }
  throw new LatexError(text, content - 1, "Grupo " + opening + closing + " sin cerrar.");
}

function citationAt(text, start) {
  let end = text[start] === "*" ? start + 1 : start;
  const notes = [];
  for (let n = 0; n < 2; n++) {
    const note = arg(text, end, "[", false);
    if (!note) break;
    notes.push(note.value);
    end = note.end;
  }
  const group = arg(text, end);
  const keys = group.value.split(",").map((key) => key.trim());
  if (keys.some((key) => !key || /[\s{}]/.test(key))) throw new LatexError(text, group.start, "Clave de cita vacía o inválida.");
  return { keys, notes, end: group.end };
}

export function scanMetadata(source) {
  const text = stripComments(source);
  const result = { caption: "", label: "", labels: [], citations: [], refs: [] };
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== "\\") continue;
    const { name, end } = commandAt(text, i);
    if (citeCommands.has(name)) {
      const cite = citationAt(text, end);
      result.citations.push(...cite.keys);
      i = cite.end - 1;
      continue;
    }
    if (["label", "ref", "pageref"].includes(name)) {
      const group = arg(text, end);
      if (name === "label") result.labels.push(group.value.trim());
      else result.refs.push(group.value.trim());
      i = group.end - 1;
      continue;
    }
    if (name === "caption" && !result.caption) {
      const offset = text[end] === "*" ? end + 1 : end;
      const short = arg(text, offset, "[", false);
      result.caption = arg(text, short?.end ?? offset).value.trim();
      // Continue scanning the caption for citations and labels.
    }
    i = end - 1;
  }
  result.labels = [...new Set(result.labels)];
  result.label = result.labels[0] ?? "";
  result.citations = [...new Set(result.citations)];
  return result;
}

function findTable(text) {
  const braces = [];
  const envs = [];
  const found = [];
  for (let i = 0; i < text.length; i++) {
    if (text[i] === "{") braces.push(i);
    if (text[i] === "}" && braces.pop() === undefined) {
      throw new LatexError(text, i, "Llave de cierre sin apertura.");
    }
    if (text[i] !== "\\") continue;
    const command = commandAt(text, i);
    if (command.name !== "begin" && command.name !== "end") {
      i = command.end - 1;
      continue;
    }
    const group = arg(text, command.end);
    const name = group.value.trim();
    if (command.name === "begin") {
      if (envs.some((env) => tableEnvs.has(env.name))) {
        throw new LatexError(text, i, "Entorno anidado no admitido en la tabla: " + name + ".");
      }
      envs.push({ name, index: i, start: group.end });
    } else {
      const env = envs.pop();
      if (env?.name !== name) throw new LatexError(text, i, "\\end{" + name + "} no coincide con la apertura.");
      if (tableEnvs.has(name)) found.push({ ...env, end: i });
    }
    i = group.end - 1;
  }
  if (braces.length) throw new LatexError(text, braces.at(-1), "Llave de apertura sin cierre.");
  if (envs.length) throw new LatexError(text, envs.at(-1).index, "Entorno sin cerrar: " + envs.at(-1).name + ".");
  if (!found.length) throw new LatexError(text, 0, "Se esperaba un entorno tabular o longtable.");
  if (found.length > 1) throw new LatexError(text, found[1].index, "Usa un archivo .tex por tabla.");
  return found[0];
}

function parseColumns(text, start, end, nesting = 0) {
  const columns = [];
  let vertical = false;
  for (let i = start; i < end; i++) {
    const type = text[i];
    if (/\s/.test(type)) continue;
    if (type === "|") {
      if (columns.length) columns.at(-1).right = true;
      else vertical = true;
      continue;
    }
    if ("@!><".includes(type)) {
      i = arg(text, i + 1).end - 1;
      continue;
    }
    if (type === "*") {
      const times = arg(text, i + 1);
      const repeated = arg(text, times.end);
      const count = Number(times.value.trim());
      if (nesting > 12 || !/^\d+$/.test(times.value.trim()) || count < 1 || count > 256) {
        throw new LatexError(text, i, "Repetición de columnas fuera de rango.");
      }
      const inner = parseColumns(text, repeated.start, repeated.end - 1, nesting + 1);
      if (columns.length + count * inner.length > 256) throw new LatexError(text, i, "Demasiadas columnas.");
      const first = columns.length;
      for (let n = 0; n < count; n++) columns.push(...inner.map((column) => ({ ...column })));
      if (vertical) columns[first].left = true;
      vertical = false;
      i = repeated.end - 1;
      continue;
    }
    if (!"lcrpmb".includes(type)) throw new LatexError(text, i, "Columna no admitida: " + type + ".");
    const width = "pmb".includes(type) ? arg(text, i + 1) : null;
    columns.push({ align: width ? "l" : type, width: width?.value.trim(), left: vertical });
    vertical = false;
    if (width) i = width.end - 1;
  }
  if (!columns.length || columns.length > 256) throw new LatexError(text, start, "Se requieren entre 1 y 256 columnas.");
  return columns;
}

function mathAt(text, i) {
  const open = text.startsWith("$$", i) ? "$$" : text[i] === "$" ? "$" : text.slice(i, i + 2);
  const close = open === "\\(" ? "\\)" : open === "\\[" ? "\\]" : open;
  const start = i + open.length;
  for (let j = start; j < text.length; j++) {
    if (text.startsWith(close, j)) return { value: text.slice(start, j), end: j + close.length };
    if (text[j] === "\\") j = commandAt(text, j).end - 1;
  }
  throw new LatexError(text, i, "Expresión matemática sin cerrar.");
}

function scanRows(text, start, end) {
  const chunks = new Map();
  const emptyRules = new Map();
  let rows = [], cells = [], before = [], depth = 0, field = start, metadataRow = false;

  function addCell(stop) {
    const leading = /^\s*/.exec(text.slice(field, stop))[0].length;
    cells.push({ index: field + leading, text: text.slice(field, stop).trim() });
  }

  function finish(stop, explicit = false) {
    if (!cells.length && !text.slice(field, stop).trim()) {
      if (!explicit || metadataRow) return;
    }
    addCell(stop);
    rows.push({ cells, before, after: [], index: cells[0].index });
    cells = [];
    before = [];
  }

  for (let i = start; i < end; i++) {
    const ch = text[i];
    if (ch === "$" || text.startsWith("\\(", i) || text.startsWith("\\[", i)) {
      i = mathAt(text, i).end - 1;
      if (i >= end) throw new LatexError(text, field, "La expresión matemática cruza el fin de la tabla.");
      continue;
    }
    if (ch === "{") depth++;
    if (ch === "}") depth--;
    if (!depth && ch === "&") {
      addCell(i);
      field = i + 1;
      continue;
    }
    if (ch !== "\\") continue;
    const { name, end: next } = commandAt(text, i);
    if (depth) {
      i = next - 1;
      continue;
    }
    const style = /^(top|mid|bottom)rule$/.exec(name);
    const isRule = style || ["hline", "cline", "cmidrule"].includes(name);
    const pending = cells.length || text.slice(field, i).trim();
    if (name === "\\" || name === "tabularnewline" || name === "cr") {
      // A longtable caption may have its own row terminator.
      finish(i, true);
      metadataRow = false;
      const offset = text[next] === "*" ? next + 1 : next;
      field = arg(text, offset, "[", false)?.end ?? offset;
    } else if (isRule || sections.has(name) || ["caption", "addlinespace"].includes(name) || (name === "label" && !pending)) {
      if (pending) {
        throw new LatexError(text, i, "Falta \\\\ antes de \\" + name + ".");
      }
      field = next;
      if (isRule) {
        if (name === "cline" || name === "cmidrule") {
          field = arg(text, next, "[", false)?.end ?? next;
          field = arg(text, field, "(", false)?.end ?? field;
          field = arg(text, field).end;
        } else if (style) field = arg(text, next, "[", false)?.end ?? next;
        before.push(({ top: "top", mid: "middle", bottom: "bottom" })[style?.[1]] ?? "line");
      } else if (sections.has(name)) {
        if (chunks.has(name)) throw new LatexError(text, i, "Sección de longtable repetida.");
        if (rows.length) rows.at(-1).after.push(...before);
        else emptyRules.set(name, before);
        chunks.set(name, rows);
        rows = [];
        before = [];
      } else if (name === "caption" || name === "label") {
        const offset = name === "caption" && text[next] === "*" ? next + 1 : next;
        field = arg(text, arg(text, offset, "[", false)?.end ?? offset).end;
        metadataRow = true;
      } else field = arg(text, next, "[", false)?.end ?? next;
    } else {
      i = next - 1;
      continue;
    }
    i = field - 1;
  }
  finish(end);
  if (rows.length) rows.at(-1).after.push(...before);
  return { rows, chunks, emptyRules };
}

function cellSpec(text, cell, column, columns) {
  let index = cell.index;
  let content = cell.text;
  let colSpan = 1, rowSpan = 1;
  let spec = columns[column];
  while (/^\\(?:multicolumn|multirow)\b/.test(content)) {
    const command = commandAt(text, index);
    const first = arg(text, command.end, "[", false);
    const size = arg(text, first?.end ?? command.end);
    const extra = command.name === "multirow" ? arg(text, size.end, "[", false) : null;
    const setting = arg(text, extra?.end ?? size.end);
    const move = command.name === "multirow" ? arg(text, setting.end, "[", false) : null;
    const value = arg(text, move?.end ?? setting.end);
    const count = Number(size.value.trim());
    const contentEnd = index + content.length;
    if (!/^\d+$/.test(size.value.trim()) || count < 1 || count > 65534 || value.end > contentEnd ||
        text.slice(value.end, contentEnd).trim()) {
      throw new LatexError(text, index, "Extensión de celda no válida.");
    }
    if (command.name === "multicolumn") {
      colSpan = count;
      const layout = parseColumns(text, setting.start, setting.end - 1);
      if (layout.length !== 1) throw new LatexError(text, setting.start, "multicolumn requiere una sola alineación.");
      const width = spec.width;
      spec = { ...layout[0], width: layout[0].width ?? (rowSpan > 1 ? width : undefined) };
    } else {
      rowSpan = count;
      if (!["*", "="].includes(setting.value.trim())) spec = { ...spec, width: setting.value.trim() };
    }
    content = value.value.trim();
    index = value.start + /^\s*/.exec(value.value)[0].length;
  }
  try {
    return { ...spec, content, column, colSpan, rowSpan, tokens: inlineTokens(content) };
  } catch (error) {
    if (error instanceof LatexError) throw new LatexError(text, index + error.position, error.reason);
    throw error;
  }
}

function layoutRows(text, rows, columns) {
  const occupied = columns.map(() => 0);
  return rows.map((row, rowIndex) => {
    let column = 0;
    const cells = [];
    for (const field of row.cells) {
      if (column >= columns.length) throw new LatexError(text, field.index, "Demasiadas celdas. Revisa los separadores &.");
      if (occupied[column] > rowIndex) {
        if (field.text) throw new LatexError(text, field.index, "Se esperaba una celda vacía bajo multirow.");
        column++;
        continue;
      }
      const cell = cellSpec(text, field, column, columns);
      for (let span = 0; span < cell.colSpan; span++) {
        if (column + span >= columns.length || occupied[column + span] > rowIndex) {
          throw new LatexError(text, field.index, "multicolumn excede el ancho o se superpone con multirow.");
        }
        occupied[column + span] = rowIndex + cell.rowSpan;
      }
      if (rowIndex + cell.rowSpan > rows.length) throw new LatexError(text, field.index, "multirow excede las filas disponibles.");
      cells.push(cell);
      column += cell.colSpan;
    }
    if (column !== columns.length) {
      throw new LatexError(text, row.index, "Fila con " + column + " de " + columns.length + " columnas. Revisa & y \\\\.");
    }
    return { ...row, cells };
  });
}

export function parseTable(source) {
  const text = stripComments(source);
  const env = findTable(text);
  const offset = env.name === "tabular*" ? arg(text, env.start).end : env.start;
  const position = arg(text, offset, "[", false);
  const preamble = arg(text, position?.end ?? offset);
  const columns = parseColumns(text, preamble.start, preamble.end - 1);
  const { rows, chunks, emptyRules } = scanRows(text, preamble.end, env.end);
  if (chunks.size && env.name !== "longtable") throw new LatexError(text, env.start, "Secciones reservadas para longtable.");
  const head = chunks.get("endfirsthead") ?? chunks.get("endhead") ?? [];
  const foot = chunks.get("endlastfoot") ?? chunks.get("endfoot") ?? [];
  const all = [...head, ...rows, ...foot];
  if (!all.length) throw new LatexError(text, preamble.end, "La tabla no tiene filas.");
  const footRules = emptyRules.get("endlastfoot") ?? (chunks.has("endlastfoot") ? [] : emptyRules.get("endfoot")) ?? [];
  all.at(-1).after.push(...footRules);
  for (const section of chunks.values()) {
    if (section !== head && section !== foot) layoutRows(text, section, columns);
  }
  const separator = all.findIndex((row, i) => i > 0 && row.before.some((rule) => rule === "middle" || rule === "line"));
  return {
    ...scanMetadata(source),
    columns,
    rows: layoutRows(text, all, columns),
    headerCount: head.length || (separator > 0 ? separator : 1),
    footerCount: foot.length,
  };
}

const symbols = { "%": "%", "&": "&", "_": "_", "#": "#", "$": "$", "{": "{", "}": "}", " ": " ",
  pm: "±", mp: "∓", times: "×", cdot: "·", le: "≤", leq: "≤", ge: "≥", geq: "≥", neq: "≠",
  textbackslash: "\\", textasciitilde: "~", textasciicircum: "^", ldots: "…", dots: "…",
  alpha: "α", beta: "β", gamma: "γ", pi: "π", degree: "°", ae: "æ", oe: "œ", ss: "ß", o: "ø" };
const accents = { "'": "\u0301", '"': "\u0308", "\u0060": "\u0300", "~": "\u0303", "^": "\u0302", "=": "\u0304", c: "\u0327" };
const styles = { textbf: "strong", textit: "em", emph: "em", texttt: "code", textsc: "span", textnormal: "span", mbox: "span" };

export function inlineTokens(text) {
  const tokens = [];
  let plain = "";
  function add(token) {
    if (plain) tokens.push({ type: "text", value: plain.replace(/[ \t\r\n]+/g, " ") });
    plain = "";
    tokens.push(token);
  }
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === "$" || text.startsWith("\\(", i) || text.startsWith("\\[", i)) {
      const math = mathAt(text, i);
      add({ type: "math", value: math.value });
      i = math.end - 1;
    } else if (ch === "{") {
      const group = arg(text, i);
      add({ type: "group", children: inlineTokens(group.value) });
      i = group.end - 1;
    } else if (ch === "\\") {
      const { name, end } = commandAt(text, i);
      i = end - 1;
      if (citeCommands.has(name)) {
        const cite = citationAt(text, end);
        add({ type: "cite", command: name, ...cite });
        i = cite.end - 1;
      } else if (Object.hasOwn(styles, name)) {
        const group = arg(text, end);
        add({ type: "style", tag: styles[name], children: inlineTokens(group.value) });
        i = group.end - 1;
      } else if (["label", "ref", "pageref"].includes(name)) {
        const group = arg(text, end);
        if (name !== "label") add({ type: "ref", value: group.value.trim() });
        i = group.end - 1;
      } else if (Object.hasOwn(accents, name)) {
        const group = arg(text, end, "{", false);
        const letter = group?.value ?? /^[A-Za-z]/.exec(text.slice(end))?.[0];
        if (letter) {
          plain += ((letter === "\\i" ? "i" : letter) + accents[name]).normalize("NFC");
          i = group ? group.end - 1 : end;
        } else plain += "\\" + name;
      } else if (name === "\\" || name === "newline" || name === "linebreak") {
        add({ type: "break" });
      } else if (Object.hasOwn(symbols, name)) {
        plain += symbols[name];
        if (text.startsWith("{}", end)) i += 2;
        else if (/^[A-Za-z]+$/.test(name) && text[end] === " ") i++;
      } else plain += "\\" + name;
    } else if (ch === "~") plain += "\u00a0";
    else plain += ch;
  }
  if (plain) tokens.push({ type: "text", value: plain.replace(/[ \t\r\n]+/g, " ") });
  return tokens;
}

export function plainText(tokens, cite = (token) => token.keys.join("; ")) {
  return tokens.map((token) => {
    if (token.children) return plainText(token.children, cite);
    if (token.type === "cite") return cite(token);
    if (token.type === "break") return "\n";
    return token.value;
  }).join("");
}

export function tableToCSV(table, format = plainText) {
  const quote = (value) => /[",\r\n]/.test(value) ? '"' + value.replaceAll('"', '""') + '"' : value;
  return table.rows.map((row) => {
    const values = table.columns.map(() => "");
    for (const cell of row.cells) values[cell.column] = quote(format(cell.tokens));
    return values.join(",");
  }).join("\r\n");
}
