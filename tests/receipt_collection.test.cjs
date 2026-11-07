const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '../templates/billing/receipt_new.html'), 'utf8');
const script = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1]
  .replace('{{ balance_amount or 0 }}', '1000');

function setup(amount) {
  const manual = {listeners: {}, addEventListener(event, fn) { this.listeners[event] = fn; }};
  const online = {listeners: {}, addEventListener(event, fn) { this.listeners[event] = fn; }};
  const input = {value: amount, addEventListener() {}, focus() {}};
  const fields = {'manual-receipt-form': manual, 'cashfree-payment-form': online,
    'amount_received': input, 'receipt_date': {}};
  const alerts = [];
  vm.runInNewContext(script, {
    document: {getElementById(id) { return fields[id]; }, querySelector() { return online; }},
    Date, alert(message) { alerts.push(message); },
  });
  return {manual, online, alerts};
}

test('manual receipt validation does not attach to the online checkout form', () => {
  const page = setup('250');
  assert.equal(typeof page.manual.listeners.submit, 'function');
  assert.equal(page.online.listeners.submit, undefined);
  let blocked = false;
  page.manual.listeners.submit({preventDefault() { blocked = true; }});
  assert.equal(blocked, false);
  assert.equal(page.alerts.length, 0);
});

for (const amount of ['0', '-10', '1000.01']) {
  test(`manual receipt still blocks invalid amount ${amount}`, () => {
    const page = setup(amount);
    let blocked = false;
    page.manual.listeners.submit({preventDefault() { blocked = true; }});
    assert.equal(blocked, true);
    assert.equal(page.alerts.length, 1);
  });
}
