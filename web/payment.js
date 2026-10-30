/* Payment-only extension. Shared room/session/revision controls stay in the pinned core. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let state = null, csrf = '', epoch = 0, busy = false, approvalKey = null;
  const pendingActions = new Set();
  const readable = value => String(value || '').replaceAll('_', ' ').toLowerCase();
  const owner = () => state?.member.role === 'owner';
  function clear() {
    epoch += 1; state = null; csrf = ''; busy = false; approvalKey = null; pendingActions.clear();
    $('payment-panel').hidden = true; $('payment-owner').hidden = true; $('payment-reconcile').hidden = true;
    for (const id of ['payment-mode', 'payment-amount', 'payment-capture', 'payment-grant', 'payment-state', 'payment-effect', 'payment-notice', 'payment-reason', 'payment-evidence']) $(id).textContent = '';
    $('payment-refund-id').value = ''; $('payment-ack').checked = false;
    $('payment-progress').replaceChildren(); $('payment-checks').replaceChildren(); $('payment-technical').open = false;
    for (const id of ['payment-grant-button', 'payment-revoke', 'payment-send']) $(id).disabled = true;
  }
  function message(text) { $('payment-notice').textContent = text; $('payment-notice').hidden = !text; }
  function render(next) {
    if (!next?.payment || !csrf) return;
    if (state && state.room.id === next.room.id && next.room.revision < state.room.revision) return;
    state = next; const payment = state.payment, operation = payment.operation, grant = payment.grant;
    const key = `${state.room.revision}:${grant.id}:${payment.case.capture}`;
    if (key !== approvalKey) { $('payment-ack').checked = false; approvalKey = key; }
    $('payment-panel').hidden = false;
    $('payment-mode').textContent = payment.mode === 'rehearsal' ? 'Fake gateway · no PayPal calls' : 'PayPal sandbox · no real money';
    $('payment-amount').textContent = `${payment.case.currency} ${payment.case.amount}`;
    $('payment-capture').textContent = payment.case.capture;
    $('payment-grant').textContent = readable(grant.status);
    if (grant.expires) $('payment-grant').textContent += ` · ${new Date(grant.expires * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    $('payment-state').textContent = operation ? `${readable(operation.state)} · request revision ${operation.revision}` : 'not sent';
    $('payment-owner').hidden = !owner();
    $('payment-effect').textContent = `I approve one ${payment.mode === 'rehearsal' ? 'simulated' : 'PayPal sandbox'} refund of ${payment.case.currency} ${payment.case.amount} for capture ${payment.case.capture}, revision ${state.room.revision}. This grant expires after five minutes.`;
    const plan = state.artifact?.revision === state.room.revision;
    $('payment-grant-button').disabled = busy || !owner() || !plan || !!operation || grant.status === 'ACTIVE' || !$('payment-ack').checked;
    $('payment-revoke').disabled = pendingActions.has('revoke') || !owner() || !grant.id || grant.status === 'REVOKED';
    $('payment-send').disabled = busy || !owner() || !plan || grant.status !== 'ACTIVE' || !!operation;
    $('payment-send').textContent = payment.mode === 'rehearsal' ? 'Simulate one refund' : 'Send one sandbox refund';
    $('payment-reason').textContent = operation?.reason || (plan ? 'Current specialist evidence is ready. The owner can review the exact effect above.' : 'Run the specialists and publish their current checked artifact below before refund approval.');
    const progress = $('payment-progress'); progress.replaceChildren();
    for (const [label, complete] of [['Prepare current evidence', plan], ['Grant exact authority', grant.status === 'ACTIVE'], ['Send once; hold uncertainty', !!operation && !['RESERVED', 'BLOCKED'].includes(operation.state)], ['Verify provider record', operation?.state === 'VERIFIED']]) {
      const row = document.createElement('li'); row.className = complete ? 'done' : ''; row.textContent = `${complete ? '✓' : '○'} ${label}`; progress.append(row);
    }
    const reconcilable = operation && !['RESERVED', 'BLOCKED'].includes(operation.state);
    $('payment-reconcile').hidden = !owner() || !reconcilable;
    if (operation?.provider_id) { $('payment-refund-id').value = operation.provider_id; $('payment-refund-id').readOnly = true; }
    else $('payment-refund-id').readOnly = false;
    $('payment-reconcile').querySelector('button').disabled = busy;
    $('payment-checks').replaceChildren();
    if (operation?.receipt) {
      for (const [label, value] of [['Amount and currency', `${operation.receipt.amount.currency_code} ${operation.receipt.amount.value} matched`], ['Capture and request', 'Matched reserved identity'], ['Provider status', operation.receipt.status], ['Final outcome', operation.state === 'VERIFIED' ? 'Verified from provider record' : 'Not yet verified complete']]) {
        const item = document.createElement('li'), title = document.createElement('span'), result = document.createElement('strong');
        title.textContent = label; result.textContent = value; item.append(title, result); $('payment-checks').append(item);
      }
    }
    $('payment-evidence').textContent = JSON.stringify(payment, null, 2);
  }
  async function action(path, body) {
    const revocation = path === 'refund-grant' && body.allow === false;
    const actionKey = revocation ? 'revoke' : path;
    if (!state || !csrf || !owner() || pendingActions.has(actionKey) || (busy && !revocation)) return;
    const current = epoch; pendingActions.add(actionKey); busy = true; render(state); message('');
    try {
      const response = await fetch(`/api/${path}`, { method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-Relayloom-CSRF': csrf }, body: JSON.stringify(body) });
      if (current !== epoch) return;
      const result = await response.json(); if (current !== epoch) return;
      if (!response.ok) throw new Error(result.error || 'The action was refused. Review the current case.');
      const refreshed = await fetch('/api/state', { credentials: 'same-origin', cache: 'no-store' });
      const next = await refreshed.json(); if (current !== epoch) return;
      if (!refreshed.ok) throw new Error('Refresh the workroom to see its latest payment record.');
      render(next);
    } catch (error) {
      if (current === epoch) message(error.message || 'Delivery could not be confirmed. Review the held operation; do not blindly resend.');
    } finally { if (current === epoch) { pendingActions.delete(actionKey); busy = pendingActions.size > 0; if (state) render(state); } }
  }
  document.addEventListener('clearwake:session', event => { csrf = event.detail.csrf; });
  document.addEventListener('clearwake:state', event => render(event.detail));
  document.addEventListener('clearwake:clear', clear);
  $('payment-ack').addEventListener('change', () => { if (state) render(state); });
  $('payment-grant-button').addEventListener('click', () => {
    if (state && $('payment-ack').checked) action('refund-grant', { revision: state.room.revision, grant_id: state.payment.grant.id, allow: true, ...state.payment.case });
  });
  $('payment-revoke').addEventListener('click', () => { if (state) action('refund-grant', { revision: state.room.revision, grant_id: state.payment.grant.id, allow: false }); });
  $('payment-send').addEventListener('click', () => { if (state) action('refund', { revision: state.room.revision, grant_id: state.payment.grant.id, ...state.payment.case }); });
  $('payment-reconcile').addEventListener('submit', event => {
    event.preventDefault();
    if (state?.payment.operation && event.currentTarget.reportValidity()) action('reconcile', { revision: state.room.revision, operation_id: state.payment.operation.id, refund_id: $('payment-refund-id').value.trim() });
  });
  const brief = document.getElementById('create-form')?.elements.brief;
  if (brief) {
    brief.defaultValue = 'Draft a fictional refund policy for the Relayloom demo store.';
    if (!brief.value) brief.value = brief.defaultValue;
  }
  clear();
  // The extension can load after the core's first event on a slow asset fetch.
  // Reconcile once, without starting work or making provider/model calls.
  (async () => {
    const current = epoch;
    try {
      const response = await fetch('/api/session', { credentials: 'same-origin', cache: 'no-store' });
      const session = await response.json();
      if (current !== epoch || !response.ok || !session.signed_in) return;
      csrf = session.csrf;
      const refreshed = await fetch('/api/state', { credentials: 'same-origin', cache: 'no-store' });
      const next = await refreshed.json();
      if (current === epoch && refreshed.ok) render(next);
    } catch (_) { /* The inherited core displays connectivity; no automatic mutation. */ }
  })();
})();
