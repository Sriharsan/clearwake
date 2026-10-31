// Full page screenshots at exact widths through the Chrome DevTools protocol (no packages; Node 22 or newer).
//   node scripts/screenshot.mjs <url> <out-prefix> [widths, default 390,1440]
// Headless Chrome keeps a minimum window width, so the width is set by device metrics emulation instead.
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [url, prefix, widthList = '390,1440'] = process.argv.slice(2);
const chrome = process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const port = 9300 + Math.floor(Math.random() * 500);
const proc = spawn(chrome, ['--headless=new', '--disable-gpu', '--hide-scrollbars', `--remote-debugging-port=${port}`,
  `--user-data-dir=${mkdtempSync(join(tmpdir(), 'cw-shot-'))}`, 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));

let target;
for (let i = 0; i < 50 && !target; i++) {
  await sleep(200);
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(t => t.type === 'page'); } catch {}
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r, { once: true }));
let id = 0; const waiting = new Map();
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (waiting.has(m.id)) { waiting.get(m.id)(m.result); waiting.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { waiting.set(++id, r); ws.send(JSON.stringify({ id, method, params })); });

await send('Page.enable');
for (const width of widthList.split(',').map(Number)) {
  const mobile = width < 768;
  await send('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile });
  await send('Page.navigate', { url });
  await sleep(2500);
  const { result } = await send('Runtime.evaluate', { expression: 'JSON.stringify([document.documentElement.scrollHeight, document.documentElement.scrollWidth])' });
  const [height, scrollWidth] = JSON.parse(result.value);
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile });
  await sleep(500);
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  writeFileSync(`${prefix}-${width}.png`, Buffer.from(shot.data, 'base64'));
  console.log(`${prefix}-${width}.png  ${width}x${height}, page scroll width ${scrollWidth}${scrollWidth > width ? '  HORIZONTAL SCROLL' : ''}`);
}
ws.close(); proc.kill();
