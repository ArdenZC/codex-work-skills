import { strict as assert } from "node:assert";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const playwrightRoot = process.env.COURSEWARE_PLAYWRIGHT_ROOT;
const playwrightModule = playwrightRoot
  ? pathToFileURL(resolve(playwrightRoot, "index.mjs")).href
  : "playwright";
const { chromium } = await import(playwrightModule);

const htmlPath = process.argv[2];
if (!htmlPath) throw new Error("usage: node tests/browser_smoke.mjs <student.html>");

const browser = await chromium.launch({
  headless: true,
  ...(process.env.COURSEWARE_BROWSER_EXECUTABLE ? { executablePath: process.env.COURSEWARE_BROWSER_EXECUTABLE } : {}),
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

try {
  await page.goto(pathToFileURL(resolve(htmlPath)).href);
  assert.equal(new URL(page.url()).protocol, "file:");
  await page.waitForFunction(() => window.__coursewareRuntime?.getPageCount() >= 2);

  const index = () => page.evaluate(() => window.__coursewareRuntime.getPageIndex());
  const count = await page.evaluate(() => window.__coursewareRuntime.getPageCount());
  assert.ok(count >= 2, "courseware must contain at least two pages");

  await page.keyboard.press("Home");
  assert.equal(await index(), 0);
  await page.keyboard.press("End");
  assert.equal(await index(), count - 1);
  await page.keyboard.press("Home");
  await page.keyboard.press("ArrowRight");
  assert.equal(await index(), 1, "ArrowRight did not advance one page");
  await page.keyboard.press("ArrowLeft");
  assert.equal(await index(), 0, "ArrowLeft did not retreat one page");

  // Discover visible authored actions page by page instead of assuming a
  // fixture-specific block or clicking controls hidden on another page.
  const actions = [];
  for (let pageIndex = 0; pageIndex < count; pageIndex += 1) {
    await page.evaluate((next) => window.__coursewareRuntime.goTo(next), pageIndex);
    const visibleActions = await page.locator(`[data-page-index="${pageIndex}"] [data-action]:visible`).evaluateAll((nodes) => nodes.map((node) => ({
      action: node.getAttribute("data-action"),
      direction: node.getAttribute("data-direction"),
    })).filter((item) => !["projection", "show-answer"].includes(item.action)));
    actions.push(...visibleActions.map((item) => ({ ...item, page: pageIndex })));
  }
  for (const item of actions) {
    await page.evaluate((pageIndex) => window.__coursewareRuntime.goTo(pageIndex), item.page);
    const before = await index();
    const direction = item.direction ? `[data-direction="${item.direction}"]` : "";
    await page.locator(`[data-page-index="${item.page}"] [data-action="${item.action}"]${direction}:visible`).first().click();
    await page.waitForTimeout(35);
    assert.equal(await index(), before, `${item.action} action advanced the deck`);
  }

  const answerButtons = page.locator('[data-action="show-answer"]');
  for (let i = 0; i < await answerButtons.count(); i += 1) {
    await answerButtons.nth(i).click();
    const answer = answerButtons.nth(i).locator("xpath=following-sibling::*[@data-answer]");
    assert.equal(await answer.isHidden(), false, "show-answer did not reveal its answer");
  }
  const steppers = page.locator("[data-stepper]:visible");
  for (let i = 0; i < await steppers.count(); i += 1) {
    const stepper = steppers.nth(i);
    const next = stepper.locator('[data-action="stepper"][data-direction="next"]');
    if (await next.count()) {
      await next.click();
      assert.notEqual(await stepper.getAttribute("data-current"), "0", "stepper next did not change state");
    }
  }

  await page.keyboard.press("Home");
  await page.locator(".slide-page.is-active").click({ position: { x: 8, y: 8 } });
  await page.waitForTimeout(80);
  assert.equal(await index(), 1, "clicking the discovered page surface did not advance one page");
  await page.keyboard.press("Home");
  await page.mouse.wheel(0, 140);
  await page.waitForTimeout(100);
  assert.equal(await index(), 1, "wheel down did not advance one page");
  await page.keyboard.press("Home");
  await page.waitForTimeout(650);
  await page.mouse.wheel(0, 1800);
  await page.waitForTimeout(100);
  assert.equal(await index(), 1, "one wheel event advanced more than one page");
  await page.waitForTimeout(650);
  await page.mouse.wheel(0, -120);
  await page.waitForTimeout(100);
  assert.equal(await index(), 0, "wheel up did not return one page");

  await page.locator(".projection-toggle").click();
  assert.equal(await index(), 0, "projection control advanced the deck");
  assert.equal(await page.locator("body").evaluate((body) => body.classList.contains("projection-mode")), true);

  for (const viewport of [[1366, 768], [1440, 900], [1920, 1080]]) {
    await page.setViewportSize({ width: viewport[0], height: viewport[1] });
    for (let pageIndex = 0; pageIndex < count; pageIndex += 1) {
      await page.evaluate((next) => window.__coursewareRuntime.goTo(next), pageIndex);
      const overflow = await page.locator(".slide-page.is-active").evaluate((slide) => {
        const layout = slide.querySelector(".slide-layout");
        const style = getComputedStyle(slide);
        const layoutStyle = layout ? getComputedStyle(layout) : null;
        return {
          pageWidth: slide.scrollWidth - slide.clientWidth,
          pageHeight: slide.scrollHeight - slide.clientHeight,
          pageOverflow: style.overflow,
          layoutWidth: layout ? layout.scrollWidth - layout.clientWidth : 0,
          layoutHeight: layout ? layout.scrollHeight - layout.clientHeight : 0,
          layoutOverflow: layoutStyle?.overflow,
        };
      });
      assert.equal(overflow.pageOverflow, "hidden");
      assert.equal(overflow.layoutOverflow, "hidden");
      assert.ok(overflow.pageWidth <= 1 && overflow.pageHeight <= 1, `page overflow at ${viewport.join("x")} page ${pageIndex}`);
      assert.ok(overflow.layoutWidth <= 1 && overflow.layoutHeight <= 1, `layout overflow at ${viewport.join("x")} page ${pageIndex}`);
    }
  }

  console.log(`courseware browser smoke: pass (${count} pages, ${actions.length} discovered actions)`);
} finally {
  await browser.close();
}
