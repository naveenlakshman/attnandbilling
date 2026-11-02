const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(process.env.STUDENT_SEARCH_TEMPLATE || path.join(__dirname,'../templates/billing/students.html'),'utf8');
const script = Array.from(html.matchAll(/<script>([\s\S]*?)<\/script>/g), match=>match[1])
  .find(text=>text.includes("const form = document.querySelector('.search-filter-section form')"));
assert.ok(script,'Student filter controller is present');

function element(value='') {
  return {value,listeners:{},addEventListener(event,fn){(this.listeners[event] ||= []).push(fn);},
    emit(event){for(const fn of this.listeners[event] || [])fn.call(this);}};
}
function setup() {
  let submissions=0;
  const timers=new Map();let timerId=0;
  const fields={search:element(),branch:element(),status:element(),batch:element()};
  fields.batch.options=[
    {value:'',getAttribute(){return null;}},
    {value:'none',getAttribute(){return null;}},
    {value:'unassigned',getAttribute(){return null;}},
    {value:'7',selected:true,getAttribute(){return 'completed';}},
    {value:'8',getAttribute(){return 'active';}},
  ];
  const form={submit(){submissions++;}};
  vm.runInNewContext(script,{
    document:{querySelector(){return form;},getElementById(id){return fields[id];}},
    setTimeout(fn){const id=++timerId;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);},
  });
  return {fields,count:()=>submissions,pause(){const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());}};
}

for (const [label,query] of [['name','Sujan H C'],['mobile','9999999999'],['registration','1516559']]) {
  test(`typing a ${label}, including pauses between characters, never submits`,()=>{
    const page=setup();
    for(let length=1;length<=query.length;length++){
      page.fields.search.value=query.slice(0,length);
      page.fields.search.emit('input');page.pause();
      assert.equal(page.count(),0,'Typing should wait for Search or Enter');
    }
    page.fields.search.value='';page.fields.search.emit('input');page.pause();
    assert.equal(page.count(),0,'Clearing the text also waits for explicit submission');
  });
}
test('intentional dropdown changes still apply filters with the entered search',()=>{
  const page=setup();page.fields.search.value='Sujan H C';
  page.fields.branch.value='1';page.fields.branch.emit('change');
  page.fields.status.value='active';page.fields.status.emit('change');
  assert.equal(page.fields.batch.value,'');
  assert.equal(page.fields.batch.options[3].hidden,true);
  assert.equal(page.fields.batch.options[4].hidden,false);
  page.fields.batch.value='8';page.fields.batch.emit('change');
  assert.equal(page.count(),3);
  assert.equal(page.fields.search.value,'Sujan H C');
});
