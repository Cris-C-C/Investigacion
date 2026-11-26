import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { inlineTokens, parseTable, plainText, scanMetadata, tableToCSV } from "../js/latex-parser.js";
import { parseBib, referenceLinks, shortAuthor } from "../js/bib-parser.js";

const fixture = (name) => readFileSync(new URL("../data/" + name, import.meta.url), "utf8");
const tex = (columns, rows) => "\\begin{tabular}{" + columns + "}\n" + rows + "\n\\end{tabular}";

test("renders the combined cells, booktabs rules and reference in the first example", () => {
  const table = parseTable(fixture("tablas/configuraciones-coorbitales.tex"));
  assert.equal(table.caption, "Configuraciones coorbitales");
  assert.equal(table.headerCount, 2);
  assert.equal(table.rows[0].cells[0].colSpan, 2);
  assert.equal(table.rows[2].cells[0].rowSpan, 2);
  assert.equal(table.rows[3].cells[0].column, 1);
  assert.deepEqual(table.rows.at(-1).after, ["bottom"]);
  assert.deepEqual(table.refs, ["tab:observables"]);
});

test("shows one longtable header and preserves the last-foot rule", () => {
  const table = parseTable(fixture("tablas/observables-coorbitales.tex"));
  assert.equal(table.caption, "Observables para detectar coorbitales");
  assert.equal(table.rows.length, 4);
  assert.equal(table.headerCount, 1);
  assert.deepEqual(table.rows.at(-1).after, ["bottom"]);
  assert.deepEqual(table.citations, ["Leleu2015", "Leleu2017"]);
});

test("tokenizes comments, optional notes, escaped characters and inline math", () => {
  const source = String.raw`\caption[Breve]{\textbf{Ángulo} \citep[según][p. 3]{a,b}}
    % \cite{omitida}
    \label{tab:x}`;
  assert.deepEqual(scanMetadata(source).citations, ["a", "b"]);
  const tokens = inlineTokens(scanMetadata(source).caption);
  assert.deepEqual(tokens.at(-1).notes, ["según", "p. 3"]);
  assert.equal(plainText(inlineTokens("\\textit{A\\&B} 85\\% v\\_1 \\pm~$x_1$")), "A&B 85% v_1 ±\u00a0x_1");
});

test("accepts nested merged cells and empty slots", () => {
  const table = parseTable(tex("*{2}{c}r", "\\multicolumn{2}{c}{\\multirow[t]{2}{*}{X}} & 1\\\\\n & & 2"));
  assert.deepEqual(table.rows[0].cells.map((cell) => [cell.colSpan, cell.rowSpan]), [[2, 2], [1, 1]]);
  assert.equal(tableToCSV(table), "X,,1\r\n,,2");
  assert.equal(parseTable(tex("c", "\\\\\nA")).rows.length, 2);
});

test("preserves quoting and spanned columns in CSV", () => {
  const table = parseTable(tex("ll", '\\multicolumn{2}{c}{Un "dato", aquí}\\\\\nA \\& B & 90\\%'));
  assert.equal(tableToCSV(table), '"Un ""dato"", aquí",\r\nA & B,90%');
});

test("rejects invalid table structure with original line numbers", () => {
  assert.throws(() => parseTable(tex("ll", "A & B & C")), /Línea 2.*Demasiadas celdas/);
  assert.throws(() => parseTable(tex("ll", "A")), /Línea 2.*1 de 2/);
  assert.throws(() => parseTable(tex("c", "$x")), /Línea 2.*matemática/);
  assert.throws(() => parseTable(tex("c", "\\multicolumn{2}{c}{X}")), /Línea 2.*excede/);
  assert.throws(() => parseTable("\\begin{tabular}{c}\nA\n\\end{longtable}"), /Línea 3.*coincide/);
  assert.throws(() => parseTable(tex("c", "\\textbf{A")), /Llave de apertura sin cierre/);
});

test("reads five entries and identifies external links", () => {
  const result = parseBib(fixture("bib/coorbitales.bib"));
  assert.deepEqual(result.errors, []);
  assert.equal(result.entries.length, 5);
  assert.deepEqual(referenceLinks(result.entries[1].fields).map(({ label }) => label), ["DOI", "ADS"]);
  assert.deepEqual(referenceLinks(result.entries[3].fields).map(({ label }) => label), ["DOI", "arXiv"]);
  assert.deepEqual(referenceLinks({ url: "javascript:alert(1)" }), []);
});

test("BibTeX handles macros, quoting, nesting, parentheses and malformed entries", () => {
  const result = parseBib([
    '@string{J = "Revista"}',
    '@comment{Ignora @article{falsa, title="Falsa"}}',
    '@article(bien, author={{Equipo de I+D}}, title=J # " {A, B}", year=2024, month=jan)',
    '@article{mal, title={Sin cierre',
    '@article{despues, title={Existe}, author={Ana}, year=2025}',
  ].join("\n"));
  assert.equal(result.errors.length, 1);
  assert.deepEqual(result.entries.map(({ key }) => key), ["bien", "despues"]);
  assert.equal(result.entries[0].fields.title, "Revista {A, B}");
  assert.equal(result.entries[0].fields.month, "January");
  assert.equal(shortAuthor(result.entries[0].fields.author), "Equipo de I+D");
  assert.equal(shortAuthor("Ana de la Cruz and Pérez, Juan and Kim, Jin"), "de la Cruz et al.");
});
