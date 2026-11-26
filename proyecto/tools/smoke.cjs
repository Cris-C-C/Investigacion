const assert = require("node:assert/strict");
const { existsSync } = require("node:fs");
const address = process.argv[2];

let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (error) {
  if (error.code !== "MODULE_NOT_FOUND") throw error;
  console.log("Playwright no está instalado. Consulta el README para activarlo.");
  process.exit(3);
}

if (address === "--available") {
  if (!existsSync(process.env.ATLAS_CHROMIUM || chromium.executablePath())) {
    console.log("Chromium no está instalado. Ejecuta npx playwright install chromium.");
    process.exitCode = 3;
  }
  return;
}

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.ATLAS_CHROMIUM || chromium.executablePath() });
  const page = await browser.newPage();
  page.setDefaultTimeout(5000);
  const problems = [];
  page.on("pageerror", (error) => problems.push("JavaScript: " + error.message));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push("Consola: " + message.text());
  });
  page.on("requestfailed", (request) => problems.push("Solicitud fallida: " + request.url()));
  let citations = 0;
  let tableCount = 0;
  try {
    const manifestResponse = await page.request.get(new URL("data/manifest.json", address).href);
    assert(manifestResponse.ok(), "No se pudo recuperar el manifiesto.");
    const manifest = await manifestResponse.json();
    await page.goto(address);
    if (manifest.tables.length) await page.locator(".sheet").waitFor();
    const links = page.locator("#table-list .table-link");
    assert.equal(await links.count(), manifest.tables.length, "La navegación debe incluir cada tabla.");
    for (const [index, item] of manifest.tables.entries()) {
      await links.nth(index).click();
      const sheet = page.locator(".sheet");
      await page.waitForFunction((path) => document.querySelector(".sheet")?.dataset.tablePath === path, item.path);
      assert.equal(await sheet.locator("table.data-table").count(), 1, "Tabla no renderizada: " + item.path);
      assert.equal(await sheet.locator(".missing-cite[data-missing-key]").count(), 0, "Cita ausente: " + item.path);
      assert.equal(await sheet.locator(".math-fallback, .katex-error").count(), 0, "KaTeX no renderizó una fórmula: " + item.path);
      const refs = sheet.locator(".references a[data-cite-key]");
      const keys = await refs.evaluateAll((elements) => elements.map((element) => element.dataset.citeKey));
      assert.deepEqual([...keys].sort(), [...item.citations].sort(), "Referencias incompletas: " + item.path);
      const citationsInTable = sheet.locator("a[data-cite-key]");
      for (const link of await citationsInTable.all()) {
        const key = await link.getAttribute("data-cite-key");
        const id = decodeURIComponent((await link.getAttribute("href")).slice(1));
        assert(await page.evaluate((id) => Boolean(document.getElementById(id)), id), "Ancla sin destino: " + key);
        await link.click();
        const dialog = page.locator("#reference-dialog[open]");
        await dialog.waitFor();
        assert.equal(await dialog.locator("#reference-key").textContent(), key);
        assert((await dialog.locator("#reference-code").textContent()).startsWith("@"), "Entrada BibTeX ausente: " + key);
        for (const external of await dialog.locator("#reference-links a").all()) {
          assert.match(await external.getAttribute("href"), /^https?:\/\//);
        }
        await dialog.getByRole("button", { name: "Cerrar" }).click();
        citations++;
      }
      tableCount++;
    }
  } catch (error) {
    problems.push(error.message);
  } finally {
    await browser.close();
  }
  if (problems.length) throw new Error(problems.join("\n"));
  console.log("Correcta. " + tableCount + " tablas y " + citations + " enlaces de referencia comprobados en Chromium.");
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
