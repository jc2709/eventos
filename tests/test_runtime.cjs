const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const root = path.resolve(__dirname,'..');
const source = fs.readFileSync(path.join(root,'web/runtime.js'),'utf8');

function setup(storage, mode='cloud') {
  const elements = new Map();
  const calls = [];
  const context = {
    window: {}, navigator: {}, document: {hidden:false,getElementById(id) {
      if(!elements.has(id)) elements.set(id,{hidden:true,textContent:''});
      return elements.get(id);
    }}, localStorage:storage,
    async fetch(url, options) {
      calls.push(url);
      if(url==='/runtime.json') return {ok:true,json:async()=>({mode})};
      if(url==='/api/lab') {
        const text = execFileSync(process.env.PYTHON || 'python3',['-c',
          'import json,sys; from eda.cloud import execute_request; print(json.dumps(execute_request(json.load(sys.stdin))))'],
          {cwd:root,input:options.body,encoding:'utf8'});
        return {ok:true,json:async()=>JSON.parse(text)};
      }
      if(url==='/api/state') return {ok:true,json:async()=>({products:[]})};
      return {ok:true,json:async()=>({ok:true})};
    }
  };
  vm.runInNewContext(source,context);
  return {runtime:context.window.aulaRuntime,elements,calls};
}
function storage() {
  const values = new Map();
  return {getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value)};
}
test('el navegador conserva pedidos y entregas al volver a abrir la página',async()=>{
  const saved = storage();
  const first = setup(saved).runtime;
  await first.initial();
  const created = await first.command('orders',{customer:'Alumno',product_id:'cuaderno',quantity:2});
  assert.equal(created.state.orders.length,1);
  assert.equal(created.state.products[0].stock,8);
  const reopened = setup(saved).runtime;
  let state = await reopened.initial();
  assert.equal(state.orders[0].id,created.result.order_id);
  state = (await reopened.command('step')).state;
  assert.equal(state.products[0].stock,6);
});
test('fallar el guardado no restaura una sesión vieja en la misma pestaña',async()=>{
  const saved = storage();
  const tab = setup(saved);
  await tab.runtime.initial();
  saved.setItem = ()=>{throw new Error('QuotaExceededError');};
  const created = await tab.runtime.command('orders',{customer:'Alumno',product_id:'cuaderno',quantity:2});
  assert.equal(created.state.orders.length,1);
  const processed = await tab.runtime.command('step');
  assert.equal(processed.state.products[0].stock,6);
  assert.match(tab.elements.get('storage-note').textContent,/mientras esta pestaña/);
});
test('el transporte local sigue utilizando las rutas existentes',async()=>{
  const tab = setup(storage(),'local');
  await tab.runtime.initial();
  await tab.runtime.command('step');
  assert.ok(tab.calls.includes('/api/state'));
  assert.ok(tab.calls.includes('/api/step'));
  assert.ok(!tab.calls.includes('/api/lab'));
});
