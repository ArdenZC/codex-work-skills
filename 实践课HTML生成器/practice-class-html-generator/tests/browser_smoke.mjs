import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const playwrightRoot = process.env.PRACTICE_PLAYWRIGHT_ROOT;
const { chromium } = await import(
  playwrightRoot ? pathToFileURL(path.join(path.resolve(playwrightRoot), "index.mjs")).href : "playwright"
);

const root = path.resolve(process.argv[2] || ".");
const viewports = [
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
];

function walkHtml(dir) {
  const files = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...walkHtml(full));
    else if (entry.isFile() && entry.name.endsWith(".html")) files.push(full);
  }
  return files;
}

function fixtureDirs(inputRoot) {
  if (fs.existsSync(path.join(inputRoot, "student", "student-task.html"))) return [inputRoot];
  return fs.readdirSync(inputRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && fs.existsSync(path.join(inputRoot, entry.name, "student", "student-task.html")))
    .map((entry) => path.join(inputRoot, entry.name));
}

function fixtureContract(dir) {
  return JSON.parse(fs.readFileSync(path.join(dir, "practice-content.json"), "utf8"));
}

function studentForbidden(contract) {
  const values = new Set(["Contract 1.0", "Practice Class"]);
  for (const task of contract.tasks || []) {
    values.add(task.id);
    for (const id of task.source_slide_ids || []) values.add(id);
  }
  for (const center of contract.learning_center || []) {
    values.add(center.id);
    if (center.interaction?.type) values.add(center.interaction.type);
  }
  for (const item of contract.study_guide || []) values.add(item.id);
  for (const item of contract.foundation_kit || []) values.add(item.id);
  for (const family of ["choice-family", "step-family", "classify-family", "reorder-family", "state-simulator-family", "multi-question-family"]) values.add(family);
  return [...values].filter(Boolean);
}

async function checkLinks(page, file, role, dir) {
  const hrefs = await page.locator("a[href]").evaluateAll((anchors) => anchors.map((anchor) => anchor.getAttribute("href")));
  for (const href of hrefs) {
    if (!href || href.startsWith("#")) continue;
    if (/^(https?:|mailto:|javascript:)/i.test(href)) throw new Error(`external link in ${file}: ${href}`);
    const target = path.resolve(path.dirname(file), href.split("#")[0]);
    if (!fs.existsSync(target)) throw new Error(`missing linked file in ${file}: ${href}`);
    const studentRoot = path.join(dir, "student") + path.sep;
    const teacherRoot = path.join(dir, "teacher") + path.sep;
    if (role === "student" && !target.startsWith(studentRoot)) throw new Error(`student link leaves student tree in ${file}: ${href}`);
    if (role === "teacher" && !target.startsWith(studentRoot) && !target.startsWith(teacherRoot)) throw new Error(`teacher link leaves package in ${file}: ${href}`);
  }
}

async function checkPageShell(page, file, dir, role, contract, viewport) {
  const body = (await page.locator("body").innerText()).trim();
  if (!body) throw new Error(`empty body: ${file}`);
  const overflow = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth }));
  if (overflow.scrollWidth > overflow.clientWidth + 1) throw new Error(`horizontal overflow in ${file}: ${JSON.stringify(overflow)}`);
  await checkLinks(page, file, role, dir);
  if (role === "student") {
    for (const value of studentForbidden(contract)) {
      if (body.includes(value)) throw new Error(`raw student value ${value} visible in ${file}`);
    }
  }
  const detail = page.locator('[data-page-kind="detail"]');
  if (await detail.count()) {
    if (await page.locator(".detail-main").count() !== 1) throw new Error(`detail main count is not one in ${file}`);
    const main = page.locator(".detail-main").first();
    const box = await main.boundingBox();
    if (!box || (viewport.width >= 1000 && (box.width < 700 || box.width > 940))) throw new Error(`detail width out of range in ${file}: ${box?.width}`);
    const layout = await main.evaluate((element) => {
      const style = getComputedStyle(element);
      return { display: style.display, borderLeftWidth: style.borderLeftWidth };
    });
    if (["grid", "flex", "inline-flex"].includes(layout.display)) throw new Error(`detail main is multi-column in ${file}`);
    if (parseFloat(layout.borderLeftWidth) > 2) throw new Error(`detail main has a thick left border in ${file}`);
    if (await page.locator(".detail-nav").count() < 2) throw new Error(`detail navigation missing in ${file}`);
    if (await page.locator(".detail-meta").count() < 1) throw new Error(`detail time/help metadata missing in ${file}`);
  }
}

async function smokeInteraction(page, file) {
  const root = page.locator("[data-interaction-root]");
  if (await root.count() !== 1) throw new Error(`learning detail must contain one interaction: ${file}`);
  const box = root.first();
  const family = await box.getAttribute("data-renderer-family");
  if (!family) throw new Error(`renderer family missing: ${file}`);
  const feedback = box.locator(".feedback").first();
  if (family === "choice-family") {
    const choice = box.locator("[data-choice]").first();
    await choice.click();
    if ((await choice.getAttribute("aria-pressed")) !== "true") throw new Error(`choice did not select: ${file}`);
    if (!(await feedback.innerText()).trim()) throw new Error(`choice feedback missing: ${file}`);
  } else if (family === "step-family") {
    const steps = box.locator(".step");
    if (await steps.count() < 2) throw new Error(`stepper has too few steps: ${file}`);
    for (let index = 1; index < await steps.count(); index += 1) {
      await box.locator("[data-next]").click();
      if (await box.locator(".step.show").count() !== 1) throw new Error(`stepper did not advance: ${file}`);
    }
  } else if (family === "classify-family") {
    const items = box.locator("[data-classify-item]");
    for (let index = 0; index < await items.count(); index += 1) {
      const item = items.nth(index);
      await item.locator("select").selectOption(await item.getAttribute("data-answer") || "");
    }
    await box.locator("[data-check]").click();
    if (!(await feedback.innerText()).trim()) throw new Error(`classify feedback missing: ${file}`);
  } else if (family === "reorder-family") {
    const list = box.locator("[data-reorder-item]");
    if (await list.count() < 2) throw new Error(`reorder has too few items: ${file}`);
    const before = await list.evaluateAll((items) => items.map((item) => item.dataset.itemId));
    await list.first().locator("[data-move-down]").click();
    const moved = await list.evaluateAll((items) => items.map((item) => item.dataset.itemId));
    if (before.join(",") === moved.join(",")) throw new Error(`reorder did not move an item: ${file}`);
    await list.nth(1).locator("[data-move-up]").click();
    await box.locator("[data-check]").click();
    if (!(await feedback.innerText()).trim()) throw new Error(`reorder feedback missing: ${file}`);
  } else if (family === "state-simulator-family") {
    const rounds = JSON.parse(await box.getAttribute("data-rounds"));
    for (let index = 0; index < rounds.length; index += 1) {
      const round = rounds[index];
      await box.locator("[data-state-a]").fill(String(round.left));
      await box.locator("[data-state-b]").fill(String(round.right));
      await box.locator("[data-state-mid]").fill(String(round.mid));
      if (round.status === "continue") {
        await box.locator("[data-state-next-a]").fill(String(round.next_left));
        await box.locator("[data-state-next-b]").fill(String(round.next_right));
      }
      await box.locator("[data-check]").click();
      if (!(await feedback.innerText()).trim()) throw new Error(`simulator feedback missing: ${file}`);
      if (round.status === "continue") await box.locator("[data-next-round]").click();
      else {
        if (await box.locator("[data-next-round]").isVisible()) throw new Error(`terminal simulator exposes next round: ${file}`);
        if (await box.locator("[data-next-state]").isVisible()) throw new Error(`terminal simulator exposes next state: ${file}`);
        if (!(await box.locator("[data-terminal-note]").isVisible())) throw new Error(`terminal note missing: ${file}`);
      }
    }
  } else if (family === "multi-question-family") {
    const questions = box.locator("[data-question]");
    if (await questions.count() < 2) throw new Error(`multi-question interaction has too few questions: ${file}`);
    for (let index = 0; index < await questions.count(); index += 1) {
      const current = questions.nth(index);
      await current.locator("[data-choice]").first().click();
      if (!(await current.locator(".feedback").innerText()).trim()) throw new Error(`multi-question feedback missing: ${file}`);
      await box.locator("[data-multi-next]").click();
    }
  } else {
    throw new Error(`unhandled renderer family ${family}: ${file}`);
  }
  return family;
}

const dirs = fixtureDirs(root);
if (!dirs.length) throw new Error(`no split fixture output directories under ${root}`);

const executablePath = process.env.PLAYWRIGHT_CHROME_EXECUTABLE || undefined;
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PRACTICE_BROWSER_EXECUTABLE || executablePath,
});
const results = [];
const families = new Set();
try {
  for (const dir of dirs) {
    const contract = fixtureContract(dir);
    const studentFiles = walkHtml(path.join(dir, "student"));
    const teacherFiles = walkHtml(path.join(dir, "teacher"));
    if (studentFiles.length < 4 || teacherFiles.length < 2) throw new Error(`incomplete page tree in ${dir}`);
    for (const file of [...studentFiles, ...teacherFiles]) {
      for (const viewport of viewports) {
        const page = await browser.newPage({ viewport });
        const requests = [];
        page.on("request", (request) => {
          if (/^https?:/i.test(request.url())) requests.push(request.url());
        });
        await page.goto(pathToFileURL(file).href, { waitUntil: "load" });
        const role = file.includes(`${path.sep}student${path.sep}`) ? "student" : "teacher";
        await checkPageShell(page, file, dir, role, contract, viewport);
        if (file.includes(`${path.sep}student${path.sep}learning${path.sep}`)) families.add(await smokeInteraction(page, file));
        if (requests.length) throw new Error(`external request in ${file}: ${requests.join(", ")}`);
        results.push({ fixture: path.basename(dir), page: path.relative(dir, file).replaceAll(path.sep, "/"), viewport: `${viewport.width}x${viewport.height}`, status: "pass" });
        await page.close();
      }
    }
  }
} finally {
  await browser.close();
}
if (families.size < 4) throw new Error(`fewer than four renderer families were smoke-tested: ${[...families].join(", ")}`);
console.log(JSON.stringify({ status: "pass", pages: results.length, renderer_families: [...families].sort(), results }, null, 2));
