// Load index.html's script against a minimal DOM shim and run every render path.
//
// Three bugs shipped that this would have caught instantly, all invisible until
// you opened the tab: a deleted `ring` variable emptied the CUES grid, a deleted
// `home` variable emptied the EDIT table, and a deleted `toggleMain` threw on the
// script's last line so window.act and window.setView were never assigned — which
// broke every button in the UI.
//
//   node vizrock/test/web/render_smoke.js vizrock/interface/web/index.html
//
// Minimal DOM shim: enough to run the render functions and surface a ReferenceError.
const mk = () => new Proxy({
  style:{setProperty(){}}, classList:{add(){},remove(){},toggle(){},contains:()=>false},
  dataset:{}, children:[], appendChild(){}, addEventListener(){},
  querySelectorAll:()=>[], querySelector:()=>mk(), getBoundingClientRect:()=>({}), contains:()=>false, remove(){}, insertBefore(){},
  set innerHTML(v){ this._h = v; }, get innerHTML(){ return this._h || ''; },
  textContent:'', value:'', getAttribute:()=>null, setAttribute(){}, blur(){}, focus(){},
}, { get:(t,k)=> k in t ? t[k] : (typeof k === 'string' ? mk() : undefined) });

global.document = {
  activeElement: null,
  getElementById: mk, createElement: mk, querySelector: mk,
  querySelectorAll: () => [], addEventListener(){}, head: mk(), body: mk(),
};
global.window = {}; global.location = { hostname: 'test' };
global.matchMedia = () => ({ matches: false });
global.setInterval = () => 0; global.setTimeout = () => 0; global.clearTimeout = () => {};
global.WebSocket = function(){ this.readyState = 3; };
global.requestAnimationFrame = () => 0;

const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
eval(script + `\n;globalThis.__ui = {state, renderCues, renderList, renderShow, render, renderInsp, renderCues, pick(id){ selected = id; },
  paintLight, LIGHT_MODES, RECT_MODES, kf};`);
const ui = globalThis.__ui;
const state = ui.state;

// the state the brain actually pushes, with the schema in current use
state.scenes = [
  {id:1,name:'Walkout',resolume:{layer:1,clip:1},dmx:{cue:'off'},
   lights:{default:{mode:'pulse',hue:160,bright:100,speed:2}}},
  {id:2,name:'Sweetness Punk Loop',main:true,resolume:{layer:1,clip:2},dmx:{cue:'off'},
   lights:{default:[{mode:'pulse',hue:40,bright:90,speed:2,seconds:12},
                    {mode:'chase',hue:64,bright:110,speed:3,seconds:8}]}},
  {id:3,name:'Two peripherals',resolume:{layer:1,clip:3},dmx:{cue:'off'},
   lights:{default:{mode:'solid',hue:10,bright:80},cabAOuter:{mode:'chase',hue:96,bright:120}}},
];
state.live = 1; state.armed = 2; state.mains = [2];
state.light_groups = {default:0, cabAOuter:1};

let failed = 0;
for (const [name, fn] of [['renderCues', ui.renderCues], ['renderList', ui.renderList],
                          ['renderShow', ui.renderShow], ['render', ui.render]]) {
  try { fn(); console.log('  ok   ' + name); }
  catch (e) { failed++; console.log('  FAIL ' + name + ' -> ' + e.constructor.name + ': ' + e.message); }
}
for (const s of state.scenes) {
  try { ui.pick(s.id); ui.renderInsp(); console.log('  ok   renderInsp scene ' + s.id); }
  catch (e) { failed++; console.log('  FAIL renderInsp scene ' + s.id + ' -> ' + e.message); }
}

// Every mode in the dropdown must paint, name a keyframe that exists, and run that
// animation on the element the keyframe can actually affect. The check derives the
// required element from the keyframe's own body rather than from RECT_MODES — using
// RECT_MODES here would just restate paintLight's decision and pass no matter what.
// A stroke/dashoffset keyframe parked on the container animates nothing at all.
const leafEl = () => ({
  style: {animation:'', opacity:'', filter:'', setProperty(){}}, dataset: {},
  setAttribute(){}, getAttribute: () => null, getBoundingClientRect: () => ({}),
});
// paintLight reaches its SVG via el.querySelector('.lpx'), so the stub must return
// the SAME child every call; the generic shim mints a fresh one each time.
const stubEl = () => { const rect = leafEl(), el = leafEl();
  el._rect = rect; el.querySelector = () => rect; el.innerHTML = ''; return el; };

const kfBody = {};
for (const block of ui.kf.textContent.split('@keyframes ').slice(1))
  kfBody[block.match(/^(\w+)/)[1]] = block;

const nameOf = n => (n.dataset.anim || n.style.animation || 'none').split(' ')[0];
for (const mode of ui.LIGHT_MODES) {
  const el = stubEl();
  try {
    ui.paintLight(el, {mode, hue: 96, bright: 120, speed: 4});
    const onRect = nameOf(el._rect), onEl = nameOf(el);
    if (onRect !== 'none' && onEl !== 'none')
      throw new Error(`animating both elements at once (${onEl} / ${onRect})`);
    const anim = onRect !== 'none' ? onRect : onEl;
    if (anim === 'none') { console.log('  ok   paintLight ' + mode + ' (static)'); continue; }
    if (!kfBody[anim]) throw new Error(`animation "${anim}" has no @keyframes`);
    const needsRect = /stroke/.test(kfBody[anim]);
    const ranOnRect = onRect !== 'none';
    if (needsRect !== ranOnRect)
      throw new Error(`"${anim}" animates ${needsRect ? 'stroke' : 'opacity'} but runs on `
                    + `the ${ranOnRect ? 'rect' : 'container'} — it will have no effect`);
    console.log('  ok   paintLight ' + mode + ' -> ' + anim
                + (needsRect ? ' (rect)' : ' (container)'));
  } catch (e) { failed++; console.log('  FAIL paintLight ' + mode + ' -> ' + e.message); }
}
process.exit(failed ? 1 : 0);
