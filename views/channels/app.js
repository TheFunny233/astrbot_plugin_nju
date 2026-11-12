const bridge = window.AstrBotPluginView;
const $ = id => document.getElementById(id);
let editing = null;
const labels = {checkin:'签到',course:'抢课',venue:'抢场'};
function message(text){$('status').textContent=text;}
function button(text, action){const b=document.createElement('button');b.textContent=text;b.onclick=async()=>{b.disabled=true;try{await action();}catch{message('操作失败，请刷新后重试');}finally{b.disabled=false;}};return b;}
function reset(){editing=null;$('form').reset();$('module').disabled=false;$('heading').textContent='新建通道';}
async function copy(url, field){
  try{await navigator.clipboard.writeText(url);message('API 已复制，请粘贴到 APP 或 Web。');}
  catch{field.focus();field.select();if(document.execCommand('copy'))message('API 已复制');else message('浏览器限制了剪贴板，请复制已选中的 API 地址。');}
}
async function load(){
 const data=await bridge.apiGet('channels');
 $('modules').textContent=Object.entries(data.modules).map(([k,v])=>`${labels[k]}：${v.implemented?(v.available?'可用':'加载失败'):'待拓展'}，待发送 ${v.pending}，失败 ${v.failed}${v.error?' · '+v.error:''}`).join(' ｜ ');
 if(!data.public_base_url)message('请先在插件配置中填写通知接口外部地址 public_base_url，再复制 API。');
 $('channels').replaceChildren();
 for(const c of data.channels){
  const section=document.createElement('section'),title=document.createElement('h2'),detail=document.createElement('p'),api=document.createElement('input');
  title.textContent=c.name;detail.textContent=`${labels[c.module]} · ${c.enabled?'已启用':'已关闭'}\n${c.targets.join('\n')}`;detail.style.whiteSpace='pre-wrap';
  api.readOnly=true;api.className='api';api.value=c.url;api.setAttribute('aria-label',`${c.name} API 地址`);
  section.append(title,detail,api);
  const cp=button('复制 API',()=>copy(c.url,api));cp.disabled=!c.url;section.append(cp);
  section.append(button('编辑',()=>{editing=c;$('heading').textContent='编辑通道';$('name').value=c.name;$('module').value=c.module;$('module').disabled=true;$('targets').value=c.targets.join('\n');$('enabled').checked=c.enabled;$('form').scrollIntoView({behavior:'smooth'});}));
  section.append(button(c.enabled?'关闭':'启用',async()=>{await bridge.apiPost('channels/save',{...c,enabled:!c.enabled});await load();}));
  section.append(button('重置 API',async()=>{if(!confirm('重置后旧地址立即失效，确定继续？'))return;await bridge.apiPost('channels/rotate',{id:c.id});await load();message('API 已重置，请重新复制。');}));
  section.append(button('删除',async()=>{if(!confirm('删除此通道及待发送通知？'))return;await bridge.apiPost('channels/delete',{id:c.id});await load();}));
  $('channels').append(section);
 }
}
$('form').onsubmit=async e=>{e.preventDefault();const submit=$('form').querySelector('[type=submit]');submit.disabled=true;try{await bridge.apiPost('channels/save',{id:editing?.id,name:$('name').value,module:$('module').value,targets:$('targets').value.split('\n').map(x=>x.trim()).filter(Boolean),enabled:$('enabled').checked});reset();await load();message('通道已保存');}catch(e){message(e.message);}finally{submit.disabled=false;}};
$('module').onchange=()=>{$('enabled').checked=$('module').value==='checkin';};
$('cancel').onclick=reset;$('refresh').onclick=()=>load().catch(()=>message('加载失败，请重试'));
await bridge.ready();await load();
