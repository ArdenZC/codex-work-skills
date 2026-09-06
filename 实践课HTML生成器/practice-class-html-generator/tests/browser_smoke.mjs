import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const playwrightRoot = process.env.PRACTICE_PLAYWRIGHT_ROOT;
const { chromium } = await import(
  playwrightRoot ? pathToFileURL(path.join(path.resolve(playwrightRoot), "index.mjs")).href : "playwright"
);

const root = path.resolve(process.argv[2] || ".");
const pages = ["student-task.html", "learning-center.html", "study-guide.html", "foundation-kit.html", "teacher-guide.html"];
const dirs = fs.readdirSync(root, { withFileTypes: true }).filter((entry) => entry.isDirectory()).map((entry) => path.join(root, entry.name));
if (!dirs.length) throw new Error(`no fixture output directories under ${root}`);
const executablePath = process.env.PLAYWRIGHT_CHROME_EXECUTABLE || undefined;
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PRACTICE_BROWSER_EXECUTABLE || executablePath,
});
const results = [];
try {
  for (const dir of dirs) {
    for (const name of pages) {
      const file = path.join(dir, name);
      if (!fs.existsSync(file)) throw new Error(`missing ${file}`);
      const page = await browser.newPage();
      const requests = [];
      page.on("request", (request) => {
        if (/^https?:/i.test(request.url())) requests.push(request.url());
      });
      await page.goto(pathToFileURL(file).href, { waitUntil: "load" });
      if (!(await page.locator("body").innerText()).trim()) throw new Error(`empty body: ${file}`);
      if (name === "learning-center.html") {
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
      }
      if (requests.length) throw new Error(`external request in ${file}: ${requests.join(", ")}`);
      results.push({ fixture: path.basename(dir), page: name, status: "pass" });
      await page.close();
    }
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify({ status: "pass", pages: results.length, results }, null, 2));
