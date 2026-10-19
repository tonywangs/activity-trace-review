'use strict';
const $ = id => document.getElementById(id);
window.captureActive = false;
let started=false, pending=false, count=0, timer=null;
$('consent').onchange=()=>{$('start').disabled=started||!$('consent').checked;};
function status(text){$('captureStatus').textContent=text;}
async function stop(reason='Stopped') {
  if(!window.captureActive)return;
  window.captureActive=false;clearTimeout(timer);
  $('stop').disabled=true;$('surface').inert=true;
  document.querySelector('.controls').classList.remove('recording');
  status('OFF — capture stopped; finishing local save…');
  try {
    const result=await window.recorderStop();
    status(`OFF — ${reason}. ${result.count} actions saved. No further activity is collected.`);
    if(result.url){$('reviewLink').href=result.url;$('reviewLink').hidden=false;}
  } catch(error) {status('OFF — save/import failed. Inspect the local destination before retrying: '+error.message);}
  finally {$('surface').inert=false;}
}
$('start').onclick=async()=>{
  if(started||!$('consent').checked)return;
  $('start').disabled=true;
  try {
    const limits=await window.recorderStart();started=true;window.captureActive=true;
    $('consent').disabled=true;$('stop').disabled=false;
    document.querySelector('.controls').classList.add('recording');
    status('● RECORDING — task panel only. Stop revokes capture.');
    timer=setTimeout(()=>stop('Five-minute limit reached'),limits.maxSeconds*1000);
  } catch(error) {status('OFF — recorder unavailable: '+error.message);}
};
$('stop').onclick=()=>stop();
const facts={earth:['Earth','Equatorial diameter: 12,756 km','science.nasa.gov/earth/facts/'],sun:['Sun','Approximate diameter: 1.4 million km','science.nasa.gov/sun/facts/']};
$('surface').addEventListener('click',async event=>{
  const button=event.target.closest('button');
  if(!event.isTrusted||!button||pending)return;
  let kind='click', value='';
  if(facts[button.id]){
    const [name,fact,source]=facts[button.id];$('planet').textContent=name;$('fact').textContent=fact;$('source').textContent='Source: '+source;value=name;
  } else if(button.id==='keep') {
    value=$('planet').textContent+': '+$('fact').textContent;$('kept').textContent=value;
  } else if(button.id==='commit') {
    kind='type';value=$('note').value;$('saved').textContent=value;
  }
  if(!window.captureActive)return;
  pending=true;$('surface').inert=true;document.body.style.overflow='hidden';
  try {
    const accepted=await window.recorderEvent({kind,label:button.dataset.label,value});
    if(accepted)count++;
    else if(window.captureActive)await stop('Capture limit reached');
    $('count').textContent=`${count} / 16 actions`;
    if(count>=16)await stop('16-action limit reached');
  } catch(error) {await stop('Capture error: '+error.message);}
  finally {pending=false;document.body.style.overflow='';if(window.captureActive)$('surface').inert=false;}
});
window.addEventListener('pagehide',()=>{window.captureActive=false;});
