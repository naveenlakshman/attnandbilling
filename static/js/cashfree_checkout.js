/* Only server verification can post a receipt; SDK results are advisory. */
(() => {
  'use strict';
  const form = document.getElementById('cashfree-payment-form');
  if (!form) return;
  const pay = document.getElementById('cashfree-pay');
  const check = document.getElementById('cashfree-verify');
  const status = document.getElementById('cashfree-status');
  const mode = form.dataset.mode || 'sandbox';
  let busy = false;
  let pendingOrder = new URLSearchParams(window.location.search).get('cashfree_order_id');
  let requestKey = null;
  let requestDetails = null;
  const paymentChoice = form.elements.payment_option;
  if (paymentChoice) {
    paymentChoice.addEventListener('change', () => {
      form.elements.amount.value = paymentChoice.selectedOptions[0].dataset.amount;
      refresh();
    });
  }
  function newRequestKey() {
    const crypto = window.crypto;
    if (crypto && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    // randomUUID requires a secure context. getRandomValues also works on the
    // local HTTP tenant hostname; keep UUID v4 randomness and format unchanged.
    if (!crypto || typeof crypto.getRandomValues !== 'function') {
      throw new Error('Secure random generation is unavailable. Use a supported browser.');
    }
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  const refresh = () => {
    pay.disabled = busy || !form.checkValidity();
    check.disabled = busy;
    check.hidden = !pendingOrder;
    if (paymentChoice) paymentChoice.disabled = busy || !!pendingOrder;
  };
  async function post(url, body, key) {
    const headers = {'Content-Type': 'application/json', 'X-CSRFToken': form.elements.csrf_token.value};
    if (key) headers['Idempotency-Key'] = key;
    const response = await fetch(url, {
      method: 'POST', credentials: 'same-origin', headers,
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'Payment request failed. Check your login and try again.');
    return result;
  }
  async function verify() {
    if (!pendingOrder) return false;
    const result = await post(form.dataset.verifyUrl.replace('ORDER_ID', encodeURIComponent(pendingOrder)));
    if (result.paid) {
      status.textContent = 'Payment verified and receipt recorded.';
      const url = new URL(window.location.href);
      url.searchParams.delete('cashfree_order_id');
      if (paymentChoice) url.searchParams.set('cashfree_paid_order', pendingOrder);
      window.location.replace(url.href);
      return result;
    }
    status.textContent = result.status === 'REVIEW'
      ? 'Cashfree received this payment, but the invoice changed. Ask an administrator to reconcile it. Do not pay again.'
      : `Payment is not confirmed (${result.status}). Check its status before paying again.`;
    return result;
  }
  form.addEventListener('input', refresh);
  check.addEventListener('click', async () => {
    busy = true; refresh();
    try { await verify(); } catch (error) { status.textContent = error.message; }
    finally { busy = false; refresh(); }
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    busy = true; refresh();
    try {
      if (typeof window.Cashfree !== 'function') throw new Error('Cashfree checkout could not load. Reload this page.');
      if (pendingOrder) {
        const result = await verify();
        if (result.paid || result.status === 'REVIEW') return;
        if (result.status === 'ACTIVE' && result.payment_session_id) {
          const cashfree = window.Cashfree({mode});
          await cashfree.checkout({paymentSessionId: result.payment_session_id, redirectTarget: '_modal'});
          await verify();
          return;
        }
        // Expired/terminated orders cannot charge again; allow a new order.
        if (!['EXPIRED', 'TERMINATED'].includes(result.status)) return;
        pendingOrder = null;
        requestDetails = null;
      }
      const body = {
        student_id: Number(form.dataset.studentId), invoice_id: Number(form.dataset.invoiceId),
        amount: form.elements.amount.value, phone: form.elements.phone.value.trim(),
        email: form.elements.email.value.trim(), name: form.elements.name.value.trim()
      };
      if (paymentChoice) body.payment_option = paymentChoice.value;
      const requestBody = JSON.stringify(body);
      if (requestBody !== requestDetails) {
        requestKey = newRequestKey();
        requestDetails = requestBody;
      }
      status.textContent = mode === 'sandbox' ? 'Opening sandbox checkout...' : 'Opening secure checkout...';
      const order = await post(form.dataset.createUrl, body, requestKey);
      pendingOrder = order.order_id;
      refresh();
      // Preserve the order reference through refreshes or a dropped connection.
      const url = new URL(window.location.href);
      url.searchParams.set('cashfree_order_id', pendingOrder);
      window.history.replaceState(null, '', url);
      const cashfree = window.Cashfree({mode});
      await cashfree.checkout({paymentSessionId: order.payment_session_id, redirectTarget: '_modal'});
      await verify();
    } catch (error) {
      status.textContent = `${error.message}${pendingOrder ? ' Use Check payment status before retrying.' : ''}`;
    } finally {
      busy = false; refresh();
    }
  });
  refresh();
  if (pendingOrder) check.click();
})();
