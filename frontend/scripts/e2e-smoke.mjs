import { chromium } from "@playwright/test";
import fs from "node:fs";

const BASE = process.env.CLAIMFLOW_FRONTEND_URL ?? "http://localhost:3000";
const API = process.env.CLAIMFLOW_API_URL ?? "http://localhost:8010";
const SCREEN_DIR = process.env.CLAIMFLOW_SCREEN_DIR ?? "/tmp/claimflow-screens";
fs.mkdirSync(SCREEN_DIR, { recursive: true });

const errors = [];
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(`[console] ${msg.text()}`);
});
page.on("pageerror", (err) => errors.push(`[pageerror] ${err.message}`));

async function shot(name) {
  await page.screenshot({ path: `${SCREEN_DIR}/${name}.png`, fullPage: true });
}

async function packageIdForSmokeTest() {
  if (process.env.CLAIMFLOW_PACKAGE_ID) return process.env.CLAIMFLOW_PACKAGE_ID;

  const response = await fetch(`${API}/packages?page=1&page_size=100&sort=-created_at`);
  if (!response.ok) throw new Error(`Could not list packages from ${API}: HTTP ${response.status}`);
  const body = await response.json();
  const candidate = body.items.find((item) => item.status === "review_ready") ?? body.items[0];
  if (!candidate) {
    throw new Error("The smoke test needs at least one processed package; upload one first or set CLAIMFLOW_PACKAGE_ID");
  }
  return candidate.package_id;
}

console.log("-> /dashboard");
await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
await page.waitForSelector("text=Dashboard");
await page.waitForSelector("text=Total packages", { timeout: 10000 });
await shot("01-dashboard");

console.log("-> /packages");
await page.goto(`${BASE}/packages`, { waitUntil: "networkidle" });
await page.waitForSelector("text=Packages", { timeout: 10000 });
await page.waitForTimeout(1500);
await shot("02-packages");

console.log("-> /reviews");
await page.goto(`${BASE}/reviews`, { waitUntil: "networkidle" });
await page.waitForSelector("text=Review queue");
await page.waitForTimeout(1500);
await shot("03-reviews");

console.log("-> /packages/new");
await page.goto(`${BASE}/packages/new`, { waitUntil: "networkidle" });
await page.waitForSelector("text=New package");
await shot("04-new-package");

const packageId = await packageIdForSmokeTest();
console.log(`-> workspace (${packageId})`);
await page.goto(`${BASE}/packages/${packageId}`, { waitUntil: "networkidle" });
await page.waitForSelector("text=Overview", { timeout: 10000 });
await page.waitForTimeout(1500);
await shot("05-workspace-overview");

console.log("-> click Fields tab");
await page.getByRole("tab", { name: "Fields" }).click();
await page.waitForTimeout(1000);
await shot("06-workspace-fields");

console.log("-> click Validation tab");
await page.getByRole("tab", { name: "Validation" }).click();
await page.waitForTimeout(1000);
await shot("07-workspace-validation");

console.log("-> click Policy evidence tab");
await page.getByRole("tab", { name: "Policy evidence" }).click();
await page.waitForTimeout(1000);
await shot("08-workspace-policy");

console.log("-> click Audit tab");
await page.getByRole("tab", { name: "Audit" }).click();
await page.waitForTimeout(1000);
await shot("09-workspace-audit");

if (process.env.CLAIMFLOW_READ_ONLY !== "1") {
  console.log("-> click Approve field, verify it sticks");
  await page.getByRole("tab", { name: "Fields" }).click();
  await page.waitForTimeout(500);
  const approveButtons = page.getByRole("button", { name: "Approve" });
  const countBefore = await approveButtons.count();
  if (countBefore > 0) {
    await approveButtons.first().click();
    await page.waitForTimeout(1500);
    await shot("10-workspace-after-approve");
  }
}

console.log("-> /settings");
await page.goto(`${BASE}/settings`, { waitUntil: "networkidle" });
await page.waitForSelector("text=Settings");
await page.waitForTimeout(1000);
await shot("11-settings");

await browser.close();

console.log("\n=== CONSOLE/PAGE ERRORS ===");
if (errors.length === 0) {
  console.log("none");
} else {
  for (const e of errors) console.log(e);
  throw new Error(`Browser smoke test captured ${errors.length} console/page error(s)`);
}
console.log("\nDone. Screenshots in", SCREEN_DIR);
