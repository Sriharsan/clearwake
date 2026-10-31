// Receipt verifier for the public site. verify.js is verdock-core's browser verifier, copied unchanged.
// Logs are fetched from this site; a visitor's own file is read with FileReader and never sent anywhere.
import { verifyLog } from './verify.js';

const $ = id => document.getElementById(id);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'text') node.textContent = value;
    else if (key === 'class') node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) if (child) node.append(child);
  return node;
}

function show(target, report) {
  target.result.textContent = report.ok ? `Pass: all ${report.count} lines, chain intact, signed by this key`
    : `Fail: ${report.failures.length} problem${report.failures.length === 1 ? '' : 's'} in ${report.count} lines`;
  target.card?.classList.toggle('ok', report.ok); target.card?.classList.toggle('bad', !report.ok);
  target.result.classList.toggle('ok', report.ok); target.result.classList.toggle('bad', !report.ok);
  target.fails.replaceChildren(...report.failures.slice(0, 5).map(f => el('li', { text: `line ${f.line}: ${f.reason}` })));
}

function tamper(text) {
  const lines = text.replace(/\n$/, '').split('\n');
  const i = Math.min(1, lines.length - 1);
  lines[i] = lines[i].replace('"success":true', '"success":false').replace('"VERIFIED"', '"MISMATCH"');
  return lines.join('\n') + '\n';
}

async function loadLogs() {
  const manifest = await (await fetch('receipts/manifest.json')).json();
  for (const log of manifest.logs) {
    const text = await (await fetch(log.file)).text();
    const result = el('p', { class: 'result', text: 'Not checked yet' });
    const fails = el('ul', { class: 'fails' });
    const card = el('article', { class: 'log' },
      el('h3', { text: log.title }),
      el('p', { text: `${manifest.label}. ${log.lines} lines.` }),
      el('p', { class: 'key', text: `Public key ${log.public_key}` }),
      result, fails);
    const target = { card, result, fails };
    const verify = el('button', { class: 'button primary', type: 'button', text: 'Verify' });
    const change = el('button', { class: 'button', type: 'button', text: 'Change one line, then verify' });
    const download = el('a', { class: 'button', href: log.file, download: '', text: 'Download' });
    verify.addEventListener('click', async () => show(target, await verifyLog(text, log.public_key)));
    change.addEventListener('click', async () => show(target, await verifyLog(tamper(text), log.public_key)));
    card.append(el('div', { class: 'actions' }, verify, change, download));
    $('logs').append(card);
  }
}

$('own').addEventListener('submit', async event => {
  event.preventDefault();
  const result = $('own-result'), file = $('own-file').files[0], key = $('own-key').value.trim();
  const target = { result, fails: el('ul') };
  result.classList.remove('ok', 'bad');
  if (!file) { result.textContent = 'Choose a file first.'; return; }
  if (!/^[0-9a-fA-F]{64}$/.test(key)) { result.textContent = 'The public key must be 64 hex characters.'; return; }
  if (file.size > 5 * 1024 * 1024) { result.textContent = 'Files up to 5 MB.'; return; }
  try {
    show(target, await verifyLog(await file.text(), key));
  } catch (error) {
    result.textContent = `Could not verify: ${error.message}`;
  }
});

loadLogs().catch(() => { $('logs').append(el('p', { class: 'note', text: 'The recorded receipts could not be loaded.' })); });
