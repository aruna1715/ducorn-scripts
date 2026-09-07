/*
 * The admin page must at least LOAD.
 *
 *     node scripts/prove_admin_page.js scripts/admin_index.html
 *
 * Exit 0 if its top-level code runs; exit 1 with the error if it does not.
 *
 * ── WHY ─────────────────────────────────────────────────────────────────
 *
 *     ReferenceError: Cannot access 'loadLogs' before initialization
 *
 * Two loaders were written as `const` arrows while the LOADERS table forty
 * lines above referenced them. A const is hoisted but not initialised, so
 * the whole page died at load — every tab, not just the new ones.
 *
 * `node --check` passed: the file is valid JavaScript. Syntax was never the
 * problem. Nothing executed the code, so nothing noticed, and the first
 * thing that ran it was a browser on the other machine.
 *
 * This stubs just enough DOM to run the page's global code: element lookups,
 * listener registration, the tab table. It also fails when querySelector
 * returns null for an id that is not in the HTML — the other way this page
 * breaks at load.
 *
 * It does not test behaviour. It answers one question: does the page come up.
 */
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]));

function node(id) {
  return { id, className: "", textContent: "", innerHTML: "", hidden: false,
           dataset: {}, style: {}, value: "recent", checked: false,
           appendChild(){}, addEventListener(){}, setAttribute(){},
           scrollIntoView(){}, querySelector(){ return node("?"); },
           removeChild(){}, remove(){}, insertBefore(){}, focus(){} };
}
const missing = [];
global.document = {
  querySelector(sel) {
    const m = /^#(.+)$/.exec(sel);
    if (m && !ids.has(m[1])) { missing.push(sel); return null; }
    return node(m ? m[1] : sel);
  },
  querySelectorAll(sel) {
    // one representative element is enough to exercise the loop body
    const n = node("stub");
    if (sel.includes("data-kind")) n.dataset.kind = "stack";
    if (sel.includes("nav button")) n.dataset.tab = "env";
    return [n];
  },
  createElement: () => node("new"),
  createDocumentFragment: () => node("frag"),
  createTextNode: () => node("text"),
  addEventListener(){},
};
global.window = { scrollTo(){}, addEventListener(){} };
global.fetch = async () => ({ ok: true, json: async () => ({}) });
global.setInterval = () => 0; global.clearInterval = () => {};
global.setTimeout = () => 0;  global.clearTimeout = () => {};

const js = html.split("<script>")[1].split("</script>")[0];
try {
  new Function(js)();
} catch (e) {
  console.log("LOAD FAILED: " + e.constructor.name + ": " + e.message);
  process.exit(1);
}
if (missing.length) {
  console.log("querySelector returned null for: " + [...new Set(missing)].join(", "));
  process.exit(1);
}
console.log("page global code executes cleanly");
