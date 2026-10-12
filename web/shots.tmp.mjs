import { chromium } from "playwright";
const [port, out, width, theme] = process.argv.slice(2);
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: Number(width), height: 900 } });
if (theme) await p.addInitScript(t => localStorage.setItem("gm-bench-theme", t), theme);
const errors = []; p.on("pageerror", e => errors.push(e.message)); p.on("console", m => m.type() === "error" && errors.push(m.text()));
for (const [name, path] of [["standings","/"],["cost","/cost/"],["tools","/tools/"],["replays","/replays/"],["method","/method/"],["v1","/v1/"]]) {
  await p.goto(`http://127.0.0.1:${port}${path}`, { waitUntil: "networkidle" }); await p.waitForTimeout(500);
  console.log(name, "h", await p.evaluate(() => document.documentElement.scrollHeight), "words", await p.evaluate(() => document.body.innerText.split(/\s+/).length));
  await p.screenshot({ path: `${out}/${name}.png`, fullPage: true });
}
console.log("errors", errors);
await b.close();
