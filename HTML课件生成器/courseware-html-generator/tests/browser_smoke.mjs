import { strict as assert } from "node:assert";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const playwrightRoot = process.env.COURSEWARE_PLAYWRIGHT_ROOT;
const playwrightModule = playwrightRoot
  ? pathToFileURL(resolve(playwrightRoot, "index.mjs")).href
  : "playwright";
const { chromium } = await import(playwrightModule);

const htmlPath = process.argv[2];
if (!htmlPath) {
  throw new Error("usage: node tests/browser_smoke.mjs <student.html>");
}

const launchOptions = { headless: true };
if (process.env.COURSEWARE_BROWSER_EXECUTABLE) {
  launchOptions.executablePath = process.env.COURSEWARE_BROWSER_EXECUTABLE;
}
const browser = await chromium.launch(launchOptions);
const page = await browser.newPage({ viewport: { width: 1440, height: 810 } });
try {
  await page.goto(pathToFileURL(resolve(htmlPath)).href);
  assert.equal(new URL(page.url()).protocol, "file:");
  await page.waitForFunction(() => window.__coursewareRuntime?.getPageCount() >= 5);

  const index = () => page.evaluate(() => window.__coursewareRuntime.getPageIndex());
  const home = async () => {
    await page.keyboard.press("Home");
    await page.waitForTimeout(80);
    assert.equal(await index(), 0);
  };
  const expectNextFrom = async (selector) => {
    await home();
    await page.locator(selector).first().click();
    await page.waitForTimeout(80);
    assert.equal(await index(), 1, `clicking ${selector} did not advance exactly one page`);
  };

  await expectNextFrom(".slide-page.is-active .slide-title");
  await expectNextFrom(".slide-page.is-active .info-card");
  await expectNextFrom(".slide-page.is-active .svg-block svg");
  await expectNextFrom(".slide-page.is-active .code-block pre");
  await home();
  await page.locator(".slide-page.is-active").click({ position: { x: 8, y: 8 } });
  await page.waitForTimeout(80);
  assert.equal(await index(), 1, "clicking the page background did not advance exactly one page");

  await home();
  await page.mouse.wheel(0, 120);
  await page.waitForTimeout(100);
  assert.equal(await index(), 1, "wheel down did not advance one page");
  await home();
  await page.waitForTimeout(600);
  await page.mouse.wheel(0, 1800);
  await page.waitForTimeout(100);
  assert.equal(await index(), 1, "one wheel event advanced more than one page");
  await page.waitForTimeout(600);
  await page.mouse.wheel(0, -120);
  await page.waitForTimeout(100);
  assert.equal(await index(), 0, "wheel up did not return one page");

  await page.evaluate(() => window.__coursewareRuntime.goTo(3));
  const beforeAnswer = await index();
  await page.locator(".quiz-block .answer-button").click();
  await page.waitForTimeout(50);
  assert.equal(await index(), beforeAnswer, "answer button caused a page advance");
  assert.equal(await page.locator(".quiz-answer").isHidden(), false, "answer did not become visible");

  await page.evaluate(() => window.__coursewareRuntime.goTo(2));
  await page.locator(".stepper-block [data-direction=next]").click();
  await page.waitForTimeout(50);
  assert.equal(await index(), 2, "stepper button caused a page advance");
  assert.equal(await page.locator(".stepper-block").getAttribute("data-current"), "1");

  await home();
  await page.locator(".projection-toggle").click();
  assert.equal(await index(), 0, "projection button caused a page advance");
  assert.equal(await page.locator("body").evaluate((body) => body.classList.contains("projection-mode")), true);

  console.log("courseware browser smoke: pass");
} finally {
  await browser.close();
}
