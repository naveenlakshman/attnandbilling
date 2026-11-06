const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../templates/billing/receivables.html'),'utf8');
const start=html.indexOf('function generateMessage(');
const end=html.indexOf('async function logReminder(',start);
const context={COMPANY_NAME:'Test Institute',CONTACT_NUMBER:'9999999999'};
vm.createContext(context);
vm.runInContext(html.slice(start,end),context);
for(const type of ['overdue','due_today','upcoming']) {
  test(type+' reminder preserves full name for SMS, copy and WhatsApp',()=>{
    const name="Mary Ann D’Souza";
    const message=context.generateMessage(type,name,1250,'INV-7','2026-11-06');
    assert.ok(message.startsWith('Dear '+name+','));
    assert.ok(message.includes('1,250') && message.includes('9999999999'));
    assert.equal(decodeURIComponent(encodeURIComponent(message)),message);
  });
}
test('blank and whitespace names are handled without losing initials',()=>{
  assert.ok(context.generateMessage('due_today','  Sujan  H C ',250,'INV-7','2026-11-06').startsWith('Dear Sujan H C,'));
  assert.ok(context.generateMessage('due_today',null,250,'INV-7','2026-11-06').startsWith('Dear Student,'));
});
