// Playwright smoke test for the Pokémon Tectonic Elo World site. Drives a dev
// server (must already be running -- see README/`npm run dev`) through the
// leaderboard -> search/sort/filter -> format switch -> trainer detail ->
// PNG export path, screenshotting each step and failing on any console/page
// error. Not part of the build; run manually or from CI as a sanity check.
//
// Usage: node verify_site.mjs [baseUrl] [outDir]
//   baseUrl defaults to http://localhost:5173/elo-world-tectonic/
//   outDir  defaults to ./verify-output/ (screenshots + downloaded PNG)
import fs from "fs";
import { chromium } from "playwright";

const baseUrl = process.argv[2] ?? "http://localhost:5173/elo-world-tectonic/";
const outDir = process.argv[3] ?? new URL("verify-output/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

fs.mkdirSync(outDir, { recursive: true });

const errors = [];
const browser = await chromium.launch();
// 1440px: wide enough for the trainer card's 3-column party grid at its
// current sprite scale (see TrainerCard.css) -- narrower viewports are a
// known follow-up, not yet covered by this script.
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(msg.text());
});
page.on("pageerror", (err) => errors.push(String(err)));

async function step(name, fn) {
  process.stdout.write(`- ${name}... `);
  await fn();
  console.log("ok");
}

await step("load leaderboard", async () => {
  await page.goto(baseUrl);
  await page.waitForSelector("text=Leaderboard");
  await page.screenshot({ path: `${outDir}/1-leaderboard.png`, fullPage: true });
});

await step("search/filter narrows results", async () => {
  await page.fill('input[placeholder="Search trainers..."]', "Rafael");
  await page.waitForTimeout(300);
  const rowCount = await page.locator("table tbody tr").count();
  if (rowCount === 0 || rowCount > 20) {
    throw new Error(`expected a small filtered result set, got ${rowCount} rows`);
  }
  await page.screenshot({ path: `${outDir}/2-search-rafael.png`, fullPage: true });
});

await step("sort by rating", async () => {
  await page.click("text=Rating");
  await page.waitForTimeout(200);
});

await step("switch format (doubles / uncursed)", async () => {
  await page.fill('input[placeholder="Search trainers..."]', "");
  await page.click("button:has-text('Doubles')");
  await page.waitForTimeout(300);
  await page.click("button:has-text('Uncursed')");
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${outDir}/3-doubles-uncursed.png`, fullPage: true });
});

await step("apply level70_only filter", async () => {
  await page.click("button:has-text('Singles')");
  await page.waitForTimeout(200);
  await page.click("button:has-text('Cursed'):not(:has-text('Excluded'))");
  await page.waitForTimeout(200);
  await page.click("button:has-text('Level 70 only')");
  await page.waitForTimeout(500);
  const url = page.url();
  if (!url.includes("/singles/cursed/level70_only")) {
    throw new Error(`expected URL to include /singles/cursed/level70_only, got ${url}`);
  }
  const rowCount = await page.locator("table tbody tr").count();
  if (rowCount !== 167) {
    throw new Error(`expected exactly 167 level70_only trainers, got ${rowCount}`);
  }
  await page.screenshot({ path: `${outDir}/3b-singles-level70-only.png`, fullPage: true });
});

await step("open trainer detail card", async () => {
  // Row 50, not 0: rank #1 is often a freshly-added/masked trainer whose
  // sprite may not be on the CDN yet (404s are handled gracefully by
  // RemoteSprite, but they're not what this step is checking).
  await page.click("table tbody tr >> nth=50");
  await page.waitForSelector(".trainer-card", { timeout: 10000 });
  await page.waitForTimeout(1500); // let sprite images load
  const overflow = await page.evaluate(() => {
    const el = document.querySelector(".trainer-card");
    return el.scrollWidth - el.clientWidth;
  });
  if (overflow > 2) throw new Error(`trainer card content overflows its container by ${overflow}px`);
  await page.screenshot({ path: `${outDir}/4-trainer-card.png`, fullPage: true });
});

await step("download card as PNG", async () => {
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 10000 }),
    page.click("button:has-text('Download as PNG')"),
  ]);
  const downloadPath = `${outDir}/${download.suggestedFilename()}`;
  await download.saveAs(downloadPath);
  const { size } = fs.statSync(downloadPath);
  if (size < 1024) throw new Error(`downloaded PNG suspiciously small (${size} bytes)`);
});

await browser.close();

if (errors.length > 0) {
  console.error("Console/page errors detected:");
  for (const e of errors) console.error(" ", e);
  process.exit(1);
}
console.log(`\nAll checks passed. Screenshots + downloaded PNG in ${outDir}`);
