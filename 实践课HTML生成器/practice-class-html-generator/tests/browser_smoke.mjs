import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const playwrightRoot = process.env.PRACTICE_PLAYWRIGHT_ROOT;
const { chromium } = await import(playwrightRoot ? pathToFileURL(path.join(path.resolve(playwrightRoot), "index.mjs")).href : "playwright");
const root = path.resolve(process.argv[2] || ".");
const viewports = [{ width: 1366, height: 768 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 }];
const studentNames = ["student/student-task.html", "student/learning-center.html", "student/study-guide.html", "student/foundation-kit.html"];
const teacherNames = ["teacher/teacher-guide.html", "teacher/teacher-reference.html"];
const families = new Set();

function fixtureDirs(inputRoot) {
  if (fs.existsSync(path.join(inputRoot, "student", "student-task.html"))) return [inputRoot];
  return fs.readdirSync(inputRoot, { withFileTypes: true }).filter((entry) => entry.isDirectory() && fs.existsSync(path.join(inputRoot, entry.name, "student", "student-task.html"))).map((entry) => path.join(inputRoot, entry.name));
}

function contract(dir) { return JSON.parse(fs.readFileSync(path.join(dir, "practice-content.json"), "utf8")); }
function pageUrl(file, hash = "") { return `${pathToFileURL(file).href}${hash ? `#${encodeURIComponent(hash)}` : ""}`; }

function forbiddenValues(data) {
  const values = new Set(["Contract 1.0", "Practice Class"]);
  for (const group of ["tasks", "learning_center", "study_guide", "foundation_kit"]) for (const item of data[group] || []) if (item?.id) values.add(item.id);
  for (const item of data.tasks || []) for (const ref of item.source_slide_ids || []) values.add(ref);
  for (const item of data.knowledge_links || []) for (const ref of item.source_slide_ids || []) values.add(ref);
  for (const value of [...Object.keys(data.source_courseware || {})]) if (value.includes("slide")) values.add(value);
  for (const value of ["choice-family", "step-family", "classify-family", "reorder-family", "state-simulator-family", "multi-question-family", "state-simulator", "multi-question", "scenario-decision", "task_id", "slide_id", "source_slide_ids", "interaction_type", "renderer_family"]) values.add(value);
  return [...values].filter(Boolean);
}

async function checkLinks(page, file, role, dir) {
  const hrefs = await page.locator("a[href]").evaluateAll((anchors) => anchors.map((anchor) => anchor.getAttribute("href")));
  for (const href of hrefs) {
    if (!href || href.startsWith("#")) continue;
    if (/^(https?:|mailto:|javascript:|file:)/i.test(href)) throw new Error(`external link in ${file}: ${href}`);
    const target = path.resolve(path.dirname(file), href.split("#")[0]);
    if (!fs.existsSync(target)) throw new Error(`missing linked file in ${file}: ${href}`);
    if (role === "student" && !target.startsWith(path.join(dir, "student") + path.sep)) throw new Error(`student link leaves student tree: ${file}: ${href}`);
  }
}

async function checkShell(page, file, role, dir, data) {
  const visible = (await page.locator("body").innerText()).toLowerCase();
  for (const value of forbiddenValues(data)) if (value && visible.includes(String(value).toLowerCase())) throw new Error(`visible machine value ${value} in ${file}`);
  if (role === "student" && visible.includes("教师参考")) throw new Error(`teacher-only navigation leaked into student text: ${file}`);
  await checkLinks(page, file, role, dir);
  const horizontal = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  if (horizontal) throw new Error(`horizontal overflow at ${file}`);
}

async function activateAndCheckPanes(page, file, expectedCount) {
  const panes = page.locator("[data-pane]");
  if (await panes.count() !== expectedCount) throw new Error(`pane count mismatch in ${file}`);
  const links = page.locator(".pane-nav [data-pane-target]");
  if (await links.count() !== expectedCount) throw new Error(`pane navigation count mismatch in ${file}`);
  for (let index = 0; index < expectedCount; index += 1) {
    const target = await links.nth(index).getAttribute("data-pane-target");
    await links.nth(index).click();
    await page.waitForTimeout(10);
    const active = page.locator("[data-pane].is-active");
    if (await active.count() !== 1) throw new Error(`multiple active panes in ${file}`);
    if ((await active.getAttribute("id")) !== target.slice(1)) throw new Error(`wrong active pane in ${file}: ${target}`);
    if (await page.locator("[data-pane]:visible").count() !== 1) throw new Error(`more than one visible pane in ${file}`);
  }
}

async function smokeChoice(box) {
  await box.locator("[data-choice]").first().click();
  await box.locator("[data-check]").click();
  if (!(await box.locator(".feedback").innerText()).trim()) throw new Error("choice feedback missing");
}

async function smokeStep(box) {
  const cards = box.locator("[data-step]");
  if (await cards.count() < 2) throw new Error("step interaction has fewer than two steps");
  await box.locator("[data-step-next]").click();
  if (!(await box.locator("[data-step-status]").innerText()).includes("2")) throw new Error("step next did not advance");
  await box.locator("[data-step-reset]").click();
  if (!(await box.locator("[data-step-status]").innerText()).includes("1")) throw new Error("step reset did not return to first step");
}

async function smokeClassify(box) {
  const feedbackItems = box.locator("[data-classify-feedback]");
  for (let i = 0; i < await feedbackItems.count(); i += 1) if (await feedbackItems.nth(i).isVisible()) throw new Error("classification feedback visible before checking");
  const items = box.locator("[data-classify-item]");
  for (let i = 0; i < await items.count(); i += 1) await items.nth(i).locator("select").selectOption((await items.nth(i).getAttribute("data-answer")) || "");
  await box.locator("[data-check]").click();
  if (!(await box.locator("[data-classify-feedback]").first().isVisible())) throw new Error("classification feedback did not reveal after checking");
}

async function moveToOrder(box, expected) {
  const list = box.locator("[data-reorder-item]");
  for (let targetIndex = 0; targetIndex < expected.length; targetIndex += 1) {
    let actual = await list.evaluateAll((items) => items.map((item) => item.dataset.itemId));
    let currentIndex = actual.indexOf(expected[targetIndex]);
    while (currentIndex > targetIndex) { await list.nth(currentIndex).locator("[data-move-up]").click(); currentIndex -= 1; }
    actual = await list.evaluateAll((items) => items.map((item) => item.dataset.itemId));
    if (actual[targetIndex] !== expected[targetIndex]) throw new Error("reorder controls could not reach expected order");
  }
}

async function smokeReorder(box) {
  const initial = JSON.parse(await box.getAttribute("data-initial-order"));
  const expected = JSON.parse(await box.getAttribute("data-correct-order"));
  if (initial.join(",") === expected.join(",")) throw new Error("reorder starts in the correct order");
  await box.locator("[data-check]").click();
  if (!(await box.locator(".feedback").evaluate((node) => node.classList.contains("wrong")))) throw new Error("reorder did not show wrong feedback first");
  await box.locator("[data-reset]").click();
  await moveToOrder(box, expected);
  await box.locator("[data-check]").click();
  if (await box.locator(".feedback").evaluate((node) => node.classList.contains("wrong"))) throw new Error("reorder remained wrong after correction");
}

async function smokeState(box) {
  const rounds = JSON.parse(await box.getAttribute("data-rounds"));
  const fields = JSON.parse(await box.getAttribute("data-state-fields"));
  if (!fields.length || !rounds.length) throw new Error("generic state contract missing");
  for (let index = 0; index < rounds.length; index += 1) {
    const expectedInputs = box.locator("[data-state-expected] input");
    for (let i = 0; i < await expectedInputs.count(); i += 1) if (await expectedInputs.nth(i).inputValue()) throw new Error("state expected field was auto-filled");
    const nextInputs = box.locator("[data-state-next] input");
    for (let i = 0; i < await nextInputs.count(); i += 1) if (await nextInputs.nth(i).isVisible() && await nextInputs.nth(i).inputValue()) throw new Error("next state field was auto-filled");
    for (const input of await expectedInputs.all()) await input.fill(JSON.parse(await input.getAttribute("data-expected-value"))?.toString?.() ?? "");
    for (const input of await nextInputs.all()) if (await input.isVisible()) await input.fill(JSON.parse(await input.getAttribute("data-expected-value"))?.toString?.() ?? "");
    await box.locator("[data-check]").click();
    if (!(await box.locator(".feedback").innerText()).trim()) throw new Error("state feedback missing");
    if (rounds[index].status === "continue") await box.locator("[data-next-round]").click();
    else {
      if (await box.locator("[data-next-round]").isVisible()) throw new Error("terminal state exposes next round");
      if (await box.locator("[data-state-next]").isVisible()) throw new Error("terminal state exposes next expected fields");
      if (!(await box.locator("[data-terminal-note]").isVisible())) throw new Error("terminal note missing");
    }
  }
  await box.locator("[data-reset]").click();
  if (!(await box.locator("[data-sim-status]").innerText()).includes("1")) throw new Error("state reset did not return to first round");
}

async function smokeMulti(box) {
  const questions = box.locator("[data-question]");
  if (await questions.count() < 2 || await box.locator("[data-question]:visible").count() !== 1) throw new Error("multi-question is not one-at-a-time");
  for (let index = 0; index < await questions.count(); index += 1) { const current = box.locator("[data-question]:visible"); await current.locator("[data-choice]").first().click(); await box.locator("[data-multi-check]").click(); if (!(await current.locator(".feedback").innerText()).trim()) throw new Error("multi-question feedback missing"); if (index + 1 < await questions.count()) await box.locator("[data-multi-next]").click(); }
}

async function smokeLearning(page, file, data, firstScreen) {
  const centers = data.learning_center || [];
  await activateAndCheckPanes(page, file, centers.length);
  for (let index = 0; index < centers.length; index += 1) {
    const hash = `lab-${centers[index].id}`;
    await page.goto(pageUrl(file, hash), { waitUntil: "load" });
    const interaction = page.locator("[data-pane].is-active [data-interaction-root]");
    const family = await interaction.getAttribute("data-renderer-family"); families.add(family);
    const box = interaction;
    const y = await box.boundingBox(); if (y) firstScreen.push(y.y);
    if (family === "choice-family") await smokeChoice(box); else if (family === "step-family") await smokeStep(box); else if (family === "classify-family") await smokeClassify(box); else if (family === "reorder-family") await smokeReorder(box); else if (family === "state-simulator-family") await smokeState(box); else if (family === "multi-question-family") await smokeMulti(box); else throw new Error(`unknown renderer family ${family}`);
  }
}

async function smokeTeacherReference(page, file, data) {
  const refs = data.teacher_reference?.task_references || [];
  await activateAndCheckPanes(page, file, refs.length);
  for (const ref of refs) { await page.goto(pageUrl(file, `reference-${ref.task_id}`), { waitUntil: "load" }); if (!(await page.locator("[data-pane].is-active .reference-answer").innerText()).trim()) throw new Error(`reference answer missing for ${ref.task_id}`); }
  const expectedVisuals = refs.filter((ref) => ref.model_visual).length;
  if (await page.locator("[data-reference-visual]").count() !== expectedVisuals) throw new Error(`reference model visual count mismatch in ${file}`);
}

async function smokeStarters(page, file, data) {
  const assets = new Map((data.starter_assets || []).map((asset) => [asset.path.replaceAll("\\", "/"), asset]));
  const links = page.locator("a[data-starter-path]");
  if (await links.count() < assets.size) throw new Error(`starter links missing in ${file}`);
  const hrefs = await links.evaluateAll((nodes) => nodes.map((node) => ({ path: node.dataset.starterPath, href: node.getAttribute("href") })));
  for (const item of hrefs) {
    if (!item.href?.startsWith("starter/")) throw new Error(`starter link is not relative in ${file}: ${item.href}`);
    if (!assets.has(item.path)) throw new Error(`unknown starter link in ${file}: ${item.path}`);
  }
  const drawioPaths = [...assets.keys()].filter((value) => value.toLowerCase().endsWith(".drawio"));
  const previews = await page.locator("[data-starter-preview-path]").evaluateAll((nodes) => nodes.map((node) => node.dataset.starterPreviewPath));
  for (const drawio of drawioPaths) if (previews.includes(drawio)) throw new Error(`draw.io raw preview exposed in ${file}: ${drawio}`);
  if ((await page.locator("body").innerText()).includes("mxGraphModel")) throw new Error(`draw.io XML exposed in ${file}`);
}

const dirs = fixtureDirs(root);
if (!dirs.length) throw new Error(`no fixture outputs under ${root}`);
const browser = await chromium.launch({ headless: true, executablePath: process.env.PRACTICE_BROWSER_EXECUTABLE || process.env.PLAYWRIGHT_CHROME_EXECUTABLE || undefined });
const results = [];
try {
  for (const dir of dirs) {
    const data = contract(dir); const firstScreen = []; const paneCounts = {};
    for (const viewport of viewports) {
      for (const relative of [...studentNames, ...teacherNames]) {
        const file = path.join(dir, ...relative.split("/")); const page = await browser.newPage({ viewport }); const requests = []; page.on("request", (request) => { if (/^https?:/i.test(request.url())) requests.push(request.url()); }); await page.goto(pathToFileURL(file).href, { waitUntil: "load" });
        const role = relative.startsWith("student/") ? "student" : "teacher"; await checkShell(page, file, role, dir, data);
        if (relative === "student/student-task.html") await smokeStarters(page, file, data); if (relative === "student/learning-center.html") await smokeLearning(page, file, data, firstScreen); else if (relative === "teacher/teacher-reference.html") await smokeTeacherReference(page, file, data); else { const expected = relative === "student/student-task.html" ? data.tasks.length : relative === "student/study-guide.html" ? data.study_guide.length : relative === "student/foundation-kit.html" ? data.foundation_kit.length : relative === "teacher/teacher-guide.html" ? (data.teacher_guide?.task_guidance || []).length : 0; if (expected) await activateAndCheckPanes(page, file, expected); }
        if (requests.length) throw new Error(`external request in ${file}: ${requests.join(", ")}`); paneCounts[relative] = await page.locator("[data-pane]").count(); results.push({ fixture: path.basename(dir), page: relative, viewport: `${viewport.width}x${viewport.height}` }); await page.close();
      }
    }
    if (firstScreen.length && Math.max(...firstScreen) >= 300) throw new Error(`first interaction begins too low in ${dir}: ${Math.max(...firstScreen)}px`);
    results.push({ fixture: path.basename(dir), main_pages: 6, pane_counts: paneCounts, first_action_y_max: Math.max(...firstScreen), renderer_families: [...families].sort() });
  }
} finally { await browser.close(); }
if (families.size < 4) throw new Error(`fewer than four renderer families were smoke-tested: ${[...families].join(", ")}`);
console.log(JSON.stringify({ status: "pass", main_pages_per_fixture: 6, viewports, renderer_families: [...families].sort(), results }, null, 2));
