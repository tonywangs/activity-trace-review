'use strict';
const $ = id => document.getElementById(id);
const token = location.hash.slice(1);
history.replaceState(null, '', location.pathname);
let state=null, review=null, current=0, bitmap=null, imageVersion=0, busy=false, controller=null;
const clone = value => structuredClone(value);
function safeReview(value){
  // Action IDs are untrusted dictionary keys, including __proto__ and constructor.
  value.replacements=Object.assign(Object.create(null),value.replacements);
  value.screenshots=Object.assign(Object.create(null),value.screenshots);
  return value;
}
function message(value, error=false){$('status').textContent=value;$('status').classList.toggle('error',error);}
async function api(path, body, signal){
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'X-Review-Token':token,...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body),signal});
  if(!response.ok){const err=await response.json();throw new Error(err.error||'Request failed');}
  return response;
}
function active(){return state.trace.actions[current];}
function shot(){const name=active().screenshot;return review.screenshots[name]??={rects:[],reviewed:false};}
function selected(){
  const actions=state.trace.actions, ids=actions.map(a=>a.id), picked=new Set();
  for(const [start,end] of review.segments){for(let i=ids.indexOf(start);i<=ids.indexOf(end);i++)picked.add(i);}
  return actions.filter((a,i)=>picked.has(i)&&!review.removed.includes(a.id));
}
function changed(){review.confirmed=false;$('confirmed').checked=false;summary();}
function summary(){
  if(!state?.source)return;
  const kept=selected(), refs=new Set(kept.map(a=>a.screenshot));
  const pending=[...refs].filter(name=>!review.screenshots[name]?.reviewed).length;
  $('counts').textContent=`${kept.length}/${state.trace.actions.length}`;
  $('readiness').textContent=`${kept.length} retained actions · ${refs.size} screenshots · ${pending} awaiting screenshot review`;
  $('export').disabled=busy||!kept.length||pending>0||!review.confirmed;
  $('saveReview').disabled=busy;
  const keptIds=new Set(kept.map(a=>a.id));
  [...$('timeline').children].forEach((el,i)=>{el.classList.toggle('omitted',!keptIds.has(state.trace.actions[i].id));el.setAttribute('aria-current',String(i===current));});
}
function node(tag, content){const el=document.createElement(tag);el.textContent=content;return el;}
function download(data,name,type){
  const url=URL.createObjectURL(data instanceof Blob?data:new Blob([data],{type}));
  const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function renderSegments(){
  $('segmentList').replaceChildren();
  review.segments.forEach((pair,i)=>{const li=node('li',pair.join(' → '));const button=node('button','Remove');button.onclick=()=>{review.segments.splice(i,1);changed();renderSegments();};li.append(button);$('segmentList').append(li);});
}
function renderRects(){
  $('rectangles').replaceChildren();
  shot().rects.forEach((r,i)=>{const li=node('li',`x ${r[0]}, y ${r[1]} · ${r[2]} × ${r[3]}`);const b=node('button','Remove');b.onclick=()=>{shot().rects.splice(i,1);shot().reviewed=false;$('reviewed').checked=false;changed();renderRects();paint();};li.append(b);$('rectangles').append(li);});
}
function paint(){
  const canvas=$('canvas'), ctx=canvas.getContext('2d');
  ctx.clearRect(0,0,canvas.width,canvas.height);
  if(bitmap)ctx.drawImage(bitmap,0,0);
  if(review&&state?.source){ctx.fillStyle='#000';for(const rect of shot().rects)ctx.fillRect(...rect);}
}
async function show(){
  if(!state?.source)return;
  const a=active(), version=++imageVersion;
  if(bitmap){bitmap.close();bitmap=null;}
  const [w,h]=state.dimensions[a.screenshot];$('canvas').width=w;$('canvas').height=h;paint();
  $('position').textContent=`${current+1} / ${state.trace.actions.length}`;
  $('previous').disabled=current===0;$('next').disabled=current===state.trace.actions.length-1;
  $('actionTitle').textContent=`${a.kind} · ${a.timestamp_ms} ms`;
  const shared=state.trace.actions.filter(x=>x.screenshot===a.screenshot).length;
  $('imageCaption').textContent=`${a.screenshot} · ${w} × ${h} pixels · shared by ${shared} actions`;
  $('fields').replaceChildren();
  for(const [key,value] of Object.entries(a.text)){
    const label=node('label','');label.className='field';label.append(node('span',key));
    const input=document.createElement('textarea');input.dataset.field=key;input.maxLength=4096;input.value=review.replacements[a.id]?.[key]??value;
    input.addEventListener('input',()=>{const fields=review.replacements[a.id]??={};if(input.value===value){delete fields[key];if(!Object.keys(fields).length)delete review.replacements[a.id];}else fields[key]=input.value;changed();});
    label.append(input,node('small',`Original: ${value}`));$('fields').append(label);
  }
  $('removed').checked=review.removed.includes(a.id);$('reviewed').checked=shot().reviewed;$('confirmed').checked=review.confirmed;
  renderRects();summary();
  try{const response=await api(`/api/image?name=${encodeURIComponent(a.screenshot)}`);const image=await createImageBitmap(await response.blob());if(version!==imageVersion){image.close();return;}bitmap=image;paint();}
  catch(e){if(version===imageVersion)message(e.message,true);}
}
function mount(snapshot){
  state=snapshot;current=0;review=snapshot.source?safeReview(clone(snapshot.review)):null;$('workbench').hidden=!snapshot.source;
  if(!snapshot.source)return;
  $('sourceBadge').textContent=snapshot.trace.synthetic?'SYNTHETIC INPUT':'NON-SYNTHETIC INPUT';
  $('timeline').replaceChildren();$('segmentStart').replaceChildren();$('segmentEnd').replaceChildren();
  snapshot.trace.actions.forEach((a,i)=>{
    const b=node('button',`${i+1}. ${a.kind}`);b.className='action';b.setAttribute('role','listitem');b.append(node('small',`${a.timestamp_ms} ms · ${a.id}`));b.onclick=()=>{current=i;show();};$('timeline').append(b);
    for(const id of ['segmentStart','segmentEnd']){const option=node('option',`${i+1}. ${a.id}`);option.value=a.id;$(id).append(option);}
  });
  $('segmentEnd').value=snapshot.trace.actions.at(-1).id;renderSegments();show();summary();
}
function navigate(index){if(!busy&&state?.source){current=Math.max(0,Math.min(state.trace.actions.length-1,index));show();}}
$('previous').onclick=()=>navigate(current-1);$('next').onclick=()=>navigate(current+1);
$('removed').onchange=()=>{const id=active().id;review.removed=review.removed.filter(x=>x!==id);if($('removed').checked)review.removed.push(id);changed();};
$('reviewed').onchange=()=>{shot().reviewed=$('reviewed').checked;changed();};
$('confirmed').onchange=()=>{review.confirmed=$('confirmed').checked;summary();};
function addRectangle(rect){
  const [w,h]=state.dimensions[active().screenshot], [x,y,rw,rh]=rect;
  if(!rect.every(Number.isInteger)||x<0||y<0||rw<1||rh<1||x+rw>w||y+rh>h||shot().rects.length>=128){message('Use an integer rectangle inside the screenshot (maximum 128 masks).',true);return;}
  shot().rects.push(rect);shot().reviewed=false;$('reviewed').checked=false;changed();renderRects();paint();message('Mask added. Review this screenshot again before export.');
}
$('addRect').onclick=()=>addRectangle(['rectX','rectY','rectW','rectH'].map(id=>Number($(id).value)));
$('clearRects').onclick=()=>{shot().rects=[];shot().reviewed=false;$('reviewed').checked=false;changed();renderRects();paint();};
let drag=null;
function pixel(event){const c=$('canvas'), b=c.getBoundingClientRect();return [Math.max(0,Math.min(c.width,Math.floor((event.clientX-b.left)*c.width/b.width))),Math.max(0,Math.min(c.height,Math.floor((event.clientY-b.top)*c.height/b.height)))];}
$('canvas').onpointerdown=e=>{if(!busy&&e.button===0){drag=pixel(e);$('canvas').setPointerCapture(e.pointerId);}};
$('canvas').onpointerup=e=>{if(!drag)return;const end=pixel(e),start=drag;drag=null;addRectangle([Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.abs(start[0]-end[0]),Math.abs(start[1]-end[1])]);};
$('canvas').onpointercancel=()=>{drag=null;};
$('addSegment').onclick=()=>{
  const start=$('segmentStart').value,end=$('segmentEnd').value,ids=state.trace.actions.map(a=>a.id);
  if(ids.indexOf(start)>ids.indexOf(end)||review.segments.length>=128){message('Choose ordered segment boundaries (maximum 128 segments).',true);return;}
  review.segments.push([start,end]);changed();renderSegments();
};
$('allSegments').onclick=()=>{review.segments=[[state.trace.actions[0].id,state.trace.actions.at(-1).id]];changed();renderSegments();};
async function operation(fn, cancellable=true){
  if(busy)return;
  busy=true;controller=new AbortController();const controls=[...document.querySelectorAll('button,input,select,textarea')].filter(el=>el.id!=='cancel');
  const disabled=controls.map(el=>el.disabled);controls.forEach(el=>el.disabled=true);$('cancel').disabled=!cancellable;
  try{await fn(controller.signal);}
  catch(e){message(e.name==='AbortError'?'Operation cancelled; no download was saved.':e.message,true);}
  finally{controls.forEach((el,i)=>el.disabled=disabled[i]);busy=false;controller=null;$('cancel').disabled=true;summary();}
}
$('cancel').onclick=()=>controller?.abort();
function base64(buffer){let output='';const bytes=new Uint8Array(buffer);for(let i=0;i<bytes.length;i+=16384)output+=String.fromCharCode(...bytes.subarray(i,i+16384));return btoa(output);}
$('import').onchange=()=>{const files=[...$('import').files];operation(async signal=>{
  if(!files.length||files.length>66||files.reduce((sum,f)=>sum+f.size,0)>24*1024*1024)throw new Error('Import limit: 66 files and 24 MiB.');
  const data=Object.create(null);for(const file of files){signal.throwIfAborted();if(Object.hasOwn(data,file.name))throw new Error('Duplicate filename');data[file.name]=base64(await file.arrayBuffer());}
  signal.throwIfAborted();$('cancel').disabled=true; // import commit is synchronous and cannot be undone by aborting transport
  const response=await api('/api/import',{files:data});mount(await response.json());message('Imported. Check each retained screenshot and text field before export.');
});$('import').value='';};
$('loadReview').onchange=()=>{const file=$('loadReview').files[0];if(!file)return;operation(async()=>{
  if(!state?.source)throw new Error('Import a trace first');if(file.size>512*1024)throw new Error('Review exceeds 512 KiB');
  const candidate=JSON.parse(await file.text());await api('/api/review',candidate);review=safeReview(candidate);renderSegments();await show();message('Source-bound review loaded.');
},false);$('loadReview').value='';};
$('saveReview').onclick=()=>operation(async()=>{const snapshot=clone(review);await api('/api/review',snapshot);download(JSON.stringify(snapshot,null,2)+'\n','review.json','application/json');message('Review saved. Keep it private and retain the unchanged source files.');},false);
$('export').onclick=()=>operation(async signal=>{const response=await api('/api/export',clone(review),signal);const blob=await response.blob();signal.throwIfAborted();download(blob,'reviewed-bundle.zip','application/zip');message('Bundle exported. Manual review cannot guarantee de-identification.');});
document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();if(state?.source&&!busy)$('saveReview').click();return;}
  if(busy||!state?.source||e.altKey||e.ctrlKey||e.metaKey||['INPUT','TEXTAREA','SELECT','BUTTON'].includes(e.target.tagName))return;
  const commands={'ArrowLeft':()=>navigate(current-1),'ArrowRight':()=>navigate(current+1),'Home':()=>navigate(0),'End':()=>navigate(state.trace.actions.length-1),'[':()=>{$('segmentStart').value=active().id;},']':()=>{$('segmentEnd').value=active().id;},'a':()=>$('addSegment').click(),'d':()=>$('removed').click(),'r':()=>$('reviewed').click()};
  if(commands[e.key]){e.preventDefault();commands[e.key]();}
});
window.addEventListener('beforeunload',e=>{if(state?.source){e.preventDefault();e.returnValue='';}});
api('/api/state').then(r=>r.json()).then(mount).catch(e=>message(`${e.message}. Open the complete URL printed by the CLI, including its token.`,true));
