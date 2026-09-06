import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const playwrightRoot = process.env.PRACTICE_PLAYWRIGHT_ROOT;
const { chromium } = await import(
  playwrightRoot ? pathToFileURL(path.join(path.resolve(playwrightRoot), "index.mjs")).href : "playwright"
);

const root = path.resolve(process.argv[2] || ".");
const studentPages = ["student/student-task.html", "student/learning-center.html", "student/study-guide.html", "student/foundation-kit.html"];
const teacherPages = ["teacher/teacher-guide.html", "teacher/teacher-reference.html"];
const hasSingleOutput = fs.existsSync(path.join(root, "student", "student-task.html"));
const dirs = hasSingleOutput
  ? [root]
  : fs.readdirSync(root, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && fs.existsSync(path.join(root, entry.name, "student", "student-task.html")))
      .map((entry) => path.join(root, entry.name));
if (!dirs.length) throw new Error(`no split fixture output directories under ${root}`);

const executablePath = process.env.PLAYWRIGHT_CHROME_EXECUTABLE || undefined;
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PRACTICE_BROWSER_EXECUTABLE || executablePath,
});
const results = [];
try {
  for (const dir of dirs) {
    for (const relative of [...studentPages, ...teacherPages]) {
      const file = path.join(dir, relative);
      if (!fs.existsSync(file)) throw new Error(`missing ${file}`);
      const page = await browser.newPage();
      const requests = [];
      page.on("request", (request) => {
        if (/^https?:/i.test(request.url())) requests.push(request.url());
      });
      await page.goto(pathToFileURL(file).href, { waitUntil: "load" });
      if (!(await page.locator("body").innerText()).trim()) throw new Error(`empty body: ${file}`);
      if (relative.endsWith("learning-center.html")) {
        const choices = page.locator("[data-choice]");
        if (await choices.count()) {
          await choices.first().click();
          if (!(await page.locator(".feedback").first().innerText()).trim()) throw new Error(`choice feedback missing: ${file}`);
        }
        const next = page.locator("[data-next]");
        if (await next.count()) {
          await next.first().click();
          if (!(await page.locator(".step.show").count())) throw new Error(`stepper did not show a step: ${file}`);
        }
        const simulatorCheck = page.locator("[data-simulator] [data-check]");
        if (await simulatorCheck.count()) {
          const simulator = page.locator("[data-simulator]").first();
          const rounds = JSON.parse(await simulator.getAttribute("data-rounds"));
          const round = rounds[0];
          await simulator.locator("[data-sim-mid]").fill(String(round.mid));
          await simulator.locator("[data-sim-next-left]").fill(String(round.next_left));
          await simulator.locator("[data-sim-next-right]").fill(String(round.next_right));
          await simulatorCheck.first().click();
          const simulatorFeedback = page.locator("[data-simulator] .feedback");
          if (!(await simulatorFeedback.innerText()).trim()) throw new Error(`simulator feedback missing: ${file}`);
          const nextRound = simulator.locator("[data-next-round]");
          if (await nextRound.isEnabled()) await nextRound.click();
        }
        const check = page.locator("[data-check]");
        if (!(await simulatorCheck.count()) && await check.count()) {
          await check.first().click();
          if (!(await page.locator(".feedback").first().innerText()).trim()) throw new Error(`check feedback missing: ${file}`);
        }
      }
      if (requests.length) throw new Error(`external request in ${file}: ${requests.join(", ")}`);
      results.push({ fixture: path.basename(dir), page: relative, status: "pass" });
      await page.close();
    }
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify({ status: "pass", pages: results.length, results }, null, 2));
