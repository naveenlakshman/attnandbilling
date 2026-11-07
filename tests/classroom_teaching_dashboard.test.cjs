const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../static/js/classroom_teaching_dashboard.js'),'utf8');

function element(dataset={}) {
  const classes = new Set();
  return {dataset,style:{},value:'',attributes:{},listeners:{},
    classList:{toggle(name,on){if(on)classes.add(name);else classes.delete(name);},contains(name){return classes.has(name);}},
    setAttribute(name,value){this.attributes[name]=value;},
    addEventListener(name,fn){this.listeners[name]=fn;},emit(name){this.listeners[name]?.();}};
}
function setup({url='https://erp.test/lms_admin/classroom-teaching?trainer_id=7',stored=null,blocked=false,empty=false}={}) {
  let hour=10;
  const names=['Alpha','Beta','Delta','Unscheduled'];
  const starts=['17:00','09:00','08:00',''];
  const cards=empty?[]:names.map((name,index)=>{
    const node=element({start:starts[index],end:starts[index]?'11:00':'',studentCount:String(index+1),
      searchText:(name+' python trainer').toLowerCase(),attendanceStatus:index%2?'completed':'pending',classStatus:index===1?'completed':'pending'});
    node.name=name;node.panel=element();node.badges=[element(),element()];
    node.querySelector=()=>node.panel;node.querySelectorAll=()=>node.badges;
    return node;
  });
  cards[0] && (cards[0].dataset.end='19:00');
  cards[2] && (cards[2].dataset.end='09:00');
  const container=element();container.children=cards.slice();
  container.querySelectorAll=()=>cards;
  container.appendChild=node=>{container.children=container.children.filter(n=>n!==node);container.children.push(node);};
  const ids=Object.fromEntries(['batchSearchInput','attendanceStatusFilter','classStatusFilter','classroomViewField','activeBatchCountBadge','activeStudentCountBadge','batchNoMatches'].map(id=>[id,element()]));
  ids.attendanceStatusFilter.value=ids.classStatusFilter.value='all';
  const buttons=['cards','list'].map(view=>element({classroomView:view}));
  const storage={value:stored,getItem(){if(blocked)throw Error('blocked');return this.value;},setItem(key,value){if(blocked)throw Error('blocked');this.value=value;}};
  const window={location:{href:url},localStorage:storage,setInterval(fn){this.tick=fn;},history:{replaceState(state,title,url){window.location.href=String(url);}}};
  const document={getElementById:id=>id==='batchCardsContainer'?(empty?null:container):ids[id],querySelectorAll:()=>buttons,addEventListener(event,fn){this.ready=fn;}};
  class Clock {getHours(){return hour;}getMinutes(){return 0;}}
  vm.runInNewContext(source,{document,window,URL,Date:Clock});document.ready();
  return {cards,container,ids,buttons,storage,window,setHour(value){hour=value;},list(){buttons[1].emit('click');},grid(){buttons[0].emit('click');}};
}

test('view switching preserves filters, visible counts and trainer URL',()=>{
  const page=setup();
  page.ids.batchSearchInput.value='Beta';page.ids.batchSearchInput.emit('input');
  page.list();
  assert.equal(page.container.classList.contains('classroom-view-list'),true);
  assert.equal(page.ids.activeBatchCountBadge.textContent,'1 Active Batches');
  assert.equal(page.ids.activeStudentCountBadge.textContent,'2 Total Students');
  assert.equal(page.cards[0].style.display,'none');
  assert.equal(page.buttons[1].attributes['aria-pressed'],'true');
  assert.equal(page.ids.classroomViewField.value,'list');
  assert.match(page.window.location.href,/trainer_id=7/);
  assert.match(page.window.location.href,/view=list/);
  assert.equal(page.storage.value,'list');
  page.grid();assert.equal(page.ids.activeBatchCountBadge.textContent,'1 Active Batches');
});
test('saved list view is restored and an explicit URL takes precedence',()=>{
  assert.equal(setup({stored:'list'}).container.classList.contains('classroom-view-list'),true);
  assert.equal(setup({stored:'list',url:'https://erp.test/?view=cards'}).container.classList.contains('classroom-view-list'),false);
  assert.equal(setup({stored:'cards',url:'https://erp.test/?view=list'}).container.classList.contains('classroom-view-list'),true);
});
test('blocked storage still permits switching',()=>{
  const page=setup({blocked:true});page.list();page.grid();
  assert.equal(page.buttons[0].attributes['aria-pressed'],'true');
});
test('combined filters and no-match feedback work without double counting list rows',()=>{
  const page=setup();page.list();
  page.ids.attendanceStatusFilter.value='completed';page.ids.attendanceStatusFilter.emit('change');
  page.ids.classStatusFilter.value='completed';page.ids.classStatusFilter.emit('change');
  assert.equal(page.ids.activeBatchCountBadge.textContent,'1 Active Batches');
  page.ids.batchSearchInput.value='absent';page.ids.batchSearchInput.emit('input');
  assert.equal(page.ids.activeStudentCountBadge.textContent,'0 Total Students');
  assert.equal(page.ids.batchNoMatches.classList.contains('d-none'),false);
  page.ids.batchSearchInput.value='Beta';page.ids.batchSearchInput.emit('input');
  assert.equal(page.ids.batchNoMatches.classList.contains('d-none'),true);
});
test('live badges update in both views and list rows sort by live status then time',()=>{
  const page=setup();page.list();
  assert.deepEqual(page.container.children.map(n=>n.name),['Beta','Delta','Alpha','Unscheduled']);
  assert.equal(page.cards[1].badges.every(b=>!b.classList.contains('d-none')),true);
  page.setHour(18);page.window.tick();
  assert.equal(page.container.children[0].name,'Alpha');
  assert.equal(page.cards[1].badges.every(b=>b.classList.contains('d-none')),true);
  page.grid();assert.equal(page.container.children[0].name,'Alpha');
});
test('empty batch pages allow toggling without errors',()=>{
  const page=setup({empty:true});page.list();page.grid();page.window.tick();
});
