// Renders a list of jobs (see catalog/render_jobs.json) to PNGs with transparent backgrounds.
// Usage: node render.cjs <jobs.json>      paths in the jobs are relative to assets/motorcycle-tag/
// Setup once: npm install (in this folder); Playwright may also need `npx playwright install chromium`.
const fs = require('fs');
const http = require('http');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.png': 'image/png', '.glb': 'model/gltf-binary' };

const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split('?')[0]);
  const file = path.join(ROOT, url);
  if (!file.startsWith(ROOT)) { res.writeHead(403); res.end(); return; }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(data);
  });
});

(async () => {
  const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}/`;
  const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 640, height: 480 } });
  page.on('pageerror', (e) => console.error('page error:', e.message));
  await page.goto(base + 'source/render/render.html');
  await page.waitForFunction('window.ready === true', null, { timeout: 60000 });
  for (const job of jobs) {
    const url = await page.evaluate((j) => window.renderJob(j), {
      ...job, model: base + job.model, skin: job.skin ? base + job.skin : null,
    });
    const out = path.join(ROOT, job.out);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, Buffer.from(url.split(',')[1], 'base64'));
    console.log('wrote', job.out);
  }
  await browser.close();
  server.close();
})();
