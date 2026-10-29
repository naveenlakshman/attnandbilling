const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {randomFillSync} = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../static/js/cashfree_checkout.js'), 'utf8');
const orderId = 'cf_1_0123456789abcdef0123456789abcdef';

function setup(responses, {pending = false, valid = true, checkoutResult = {}, cryptoApi,
                          origin = 'https://tenant.example'} = {}) {
  const calls = [], checkouts = [], navigations = [], handlers = {};
  const fields = Object.fromEntries(Object.entries({
    amount:'750.00', phone:'9876543210', email:'student@example.com', name:'Student', csrf_token:'csrf-test'
  }).map(([name,value]) => [name,{value}]));
  const form = {
    dataset:{createUrl:'/billing/cashfree/orders', verifyUrl:'/billing/cashfree/orders/ORDER_ID/verify',
             studentId:'100', invoiceId:'101'},
    elements:fields, checkValidity:() => valid, reportValidity:() => valid,
    addEventListener:(name,handler) => { handlers[name] = handler; }
  };
  const pay = {}, status = {}, check = {
    addEventListener:(name,handler) => { handlers.check = handler; },
    click:() => { startup = handlers.check(); }
  };
  let startup = Promise.resolve();
  let sequence = 0;
  const window = {
    location:{href:origin + '/billing/invoice/101' + (pending ? '?cashfree_order_id=' + orderId : ''),
              search:pending ? '?cashfree_order_id=' + orderId : '', replace:url => navigations.push(url)},
    history:{replaceState:(_state,_title,url) => { window.location.href = String(url); }},
    crypto:cryptoApi === undefined
      ? {randomUUID:() => '00000000-0000-4000-8000-' + String(++sequence).padStart(12,'0')}
      : cryptoApi,
    Cashfree:options => {
      assert.equal(options.mode, 'sandbox');
      return {checkout:async options => {
        checkouts.push(options);
        if (typeof checkoutResult === 'function') return checkoutResult();
        if (checkoutResult instanceof Error) throw checkoutResult;
        return checkoutResult;
      }};
    }
  };
  const nodes = {'cashfree-payment-form':form, 'cashfree-pay':pay, 'cashfree-verify':check, 'cashfree-status':status};
  vm.runInNewContext(source, {
    window, document:{getElementById:id => nodes[id]}, URL, URLSearchParams,
    fetch:async (url,options) => {
      calls.push({url,options});
      assert.ok(responses.length, 'Unexpected backend request: ' + url);
      const response = responses.shift();
      if (response instanceof Error) throw response;
      return {ok:response.ok !== false, json:async () => response.body};
    }
  });
  return {calls,checkouts,navigations,form,pay,check,status,window,startup,
          submit:() => handlers.submit({preventDefault(){}}), recheck:() => handlers.check()};
}

const created = () => ({body:{order_id:orderId,payment_session_id:'session-test'}});
const active = () => ({body:{status:'ACTIVE',paid:false,payment_session_id:'session-test'}});
const paid = () => ({body:{status:'PAID',paid:true,receipt_id:5}});

test('keeps payment unavailable until the form is valid', async () => {
  const ui = setup([], {valid:false});
  assert.equal(ui.pay.disabled, true);
  await ui.submit();
  assert.equal(ui.calls.length, 0);
});

test('creates a CSRF-protected order, opens modal, then asks backend to verify', async () => {
  const ui = setup([created(), paid()]);
  await ui.submit();
  assert.equal(ui.calls[0].url, '/billing/cashfree/orders');
  assert.equal(ui.calls[0].options.headers['X-CSRFToken'], 'csrf-test');
  assert.ok(ui.calls[0].options.headers['Idempotency-Key']);
  assert.equal(ui.calls[0].options.credentials, 'same-origin');
  assert.equal(JSON.parse(ui.calls[0].options.body).invoice_id, 101);
  assert.equal(JSON.parse(ui.calls[0].options.body).amount, '750.00');
  assert.equal(ui.checkouts[0].redirectTarget, '_modal');
  assert.equal(ui.checkouts[0].paymentSessionId, 'session-test');
  assert.equal(ui.calls[1].url, `/billing/cashfree/orders/${orderId}/verify`);
  assert.equal(ui.navigations.length, 1);
});

test('SDK paymentDetails alone cannot display successful payment', async () => {
  const ui = setup([created(), active()], {checkoutResult:{paymentDetails:{paymentMessage:'Success'}}});
  await ui.submit();
  assert.equal(ui.navigations.length, 0);
  assert.match(ui.status.textContent, /not confirmed/);
  assert.equal(ui.check.hidden, false);
});

test('reuses request key after a creation timeout', async () => {
  const ui = setup([new Error('Network unavailable'), created(), paid()]);
  await ui.submit();
  await ui.submit();
  assert.equal(ui.calls[0].options.headers['Idempotency-Key'], ui.calls[1].options.headers['Idempotency-Key']);
});

test('returns configuration errors without opening checkout', async () => {
  const ui = setup([{ok:false,body:{error:'Set the complete sandbox credentials.'}}]);
  await ui.submit();
  assert.equal(ui.checkouts.length, 0);
  assert.match(ui.status.textContent, /complete sandbox credentials/);
  assert.equal(ui.pay.disabled, false);
});

test('return URL verifies and resumes the same active order without creating another', async () => {
  const ui = setup([active(), active(), paid()], {pending:true});
  await ui.startup;
  await ui.submit();
  assert.equal(ui.calls.length, 3);
  assert.ok(ui.calls.every(call => call.url.endsWith('/verify')));
  assert.equal(ui.checkouts.length, 1);
  assert.equal(ui.navigations.length, 1);
});

test('reconciliation review blocks another checkout', async () => {
  const review = () => ({body:{status:'REVIEW',paid:false,receipt_id:null}});
  const ui = setup([review(), review()], {pending:true});
  await ui.startup;
  await ui.submit();
  assert.equal(ui.checkouts.length, 0);
  assert.ok(ui.calls.every(call => call.url.endsWith('/verify')));
  assert.match(ui.status.textContent, /Do not pay again/);
});

test('rejected checkout leaves a status check that can confirm a late payment', async () => {
  const ui = setup([created(), paid()], {checkoutResult:new Error('Popup closed')});
  await ui.submit();
  assert.equal(ui.check.hidden, false);
  assert.match(ui.status.textContent, /Check payment status/);
  await ui.recheck();
  assert.equal(ui.navigations.length, 1);
});

test('duplicate clicks while checkout is open cannot create another order', async () => {
  let release;
  const popup = new Promise(resolve => { release = resolve; });
  const ui = setup([created(), active()], {checkoutResult:() => popup});
  const first = ui.submit();
  await new Promise(resolve => setImmediate(resolve));
  await ui.submit();
  assert.equal(ui.calls.length, 1);
  release({});
  await first;
  assert.equal(ui.checkouts.length, 1);
});

test('HTTP tenant checkout works without randomUUID and sends a valid UUID v4 request key', async () => {
  const ui = setup([created(), paid()], {
    origin:'http://globalit.127-0-0-1.nip.io:8080',
    cryptoApi:{getRandomValues:bytes => randomFillSync(bytes)}
  });
  await ui.submit();
  assert.match(ui.calls[0].options.headers['Idempotency-Key'],
               /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(ui.checkouts.length, 1);
  assert.equal(ui.checkouts[0].redirectTarget, '_modal');
  assert.equal(ui.navigations.length, 1);
});

test('fallback request key stays the same when retrying a creation timeout', async () => {
  let generated = 0;
  const ui = setup([new Error('Network unavailable'), created(), paid()], {
    cryptoApi:{getRandomValues:bytes => { generated++; return randomFillSync(bytes); }}
  });
  await ui.submit();
  await ui.submit();
  assert.equal(generated, 1);
  assert.equal(ui.calls[0].options.headers['Idempotency-Key'], ui.calls[1].options.headers['Idempotency-Key']);
});

test('changed payment details get a different fallback request key', async () => {
  const ui = setup([new Error('Network unavailable'), created(), paid()], {
    cryptoApi:{getRandomValues:bytes => randomFillSync(bytes)}
  });
  await ui.submit();
  ui.form.elements.amount.value = '500.00';
  await ui.submit();
  assert.notEqual(ui.calls[0].options.headers['Idempotency-Key'], ui.calls[1].options.headers['Idempotency-Key']);
});

for (const cryptoApi of [null, {}]) {
  test(`missing secure random APIs (${JSON.stringify(cryptoApi)}) stop before creating an order`, async () => {
    const ui = setup([], {cryptoApi});
    await ui.submit();
    assert.equal(ui.calls.length, 0);
    assert.equal(ui.checkouts.length, 0);
    assert.match(ui.status.textContent, /Secure random generation is unavailable/);
    assert.equal(ui.pay.disabled, false);
  });
}
