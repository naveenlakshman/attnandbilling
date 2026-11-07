/* Sharing controls on the staff invoice page; independent of checkout state. */
(() => {
  'use strict';
  const button = document.getElementById('cashfree-copy-link');
  const input = document.getElementById('student-payment-url');
  const label = document.getElementById('cashfree-copy-label');
  const feedback = document.getElementById('cashfree-copy-feedback');
  if (!button || !input || !label || !feedback) return;
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        await navigator.clipboard.writeText(input.value);
      } else {
        input.focus();
        input.select();
        input.setSelectionRange(0, input.value.length);
        if (!document.execCommand('copy')) throw new Error('Clipboard unavailable');
      }
      label.textContent = 'Copied!';
      feedback.textContent = 'Payment link copied.';
      setTimeout(() => { label.textContent = 'Copy link'; }, 2000);
    } catch (_) {
      input.focus();
      input.select();
      feedback.textContent = 'Select and copy the link above.';
    } finally {
      button.disabled = false;
    }
  });
})();
