const bridge = window.AstrBotPluginView;
const $ = id => document.getElementById(id);
const labels = {checkin:'签到',course:'抢课',venue:'抢场'};
const states = {running:'运行中',pending:'连接中',stopped:'未连接',disabled:'已停用',error:'连接异常'};
let editing = null, platforms = [], preserveLegacy = false, busy = false;
function message(text, error=false){$('status').textContent=text;$('status').dataset.error=String(error);}
function element(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
function button(text,action,className){const b=element('button',text,className);b.type='button';b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){message(e.message||'操作失败，请重试',true);}finally{b.disabled=false;}};return b;}
function updateSave(){
 const selected=platforms.find(p=>p.id===$('platform').value);
 const unsupported=selected?.proactive===false;
 if(!preserveLegacy&&unsupported)$('enabled').checked=false;
 $('enabled').disabled=busy||(!preserveLegacy&&unsupported);
 $('save').disabled=busy||(!preserveLegacy&&!selected);
 $('platform-hint').textContent=platforms.length?'列出所有已配置的机器人；只有一个时自动选择。':'还没有可选择的机器人。请先在 AstrBot 的消息平台中添加任意协议的机器人，再刷新此页。';
 $('group-label').textContent=selected?.group_label||'群聊 / 频道 ID';
 $('user-label').textContent=selected?.user_label||'私聊会话 ID';
 $('groups').placeholder=selected?.group_placeholder||'填写该协议的群聊或频道 ID';
 $('users').placeholder=selected?.user_placeholder||'填写该协议的私聊目标 ID';
 for(const id of ['groups','users'])$(id).inputMode=selected?.id_format==='qq_number'?'numeric':'text';
 let hint=selected?.hint||'选定机器人后，会显示该协议的接收目标格式。';
 if(unsupported)hint+=' 该适配器不支持主动通知，通道只能保存为关闭状态。';
 else if(selected?.proactive===null)hint+=' 机器人尚未运行，主动通知能力将在连接后检查。';
 $('protocol-hint').textContent=hint;
}
function fillPlatforms(selected=''){
 const select=$('platform');select.replaceChildren();
 if(platforms.length!==1)select.append(new Option(platforms.length?'请选择发送消息的机器人':'请先添加机器人',''));
 for(const p of platforms)select.append(new Option(`${p.label} · ${p.protocol_label||p.type} · ${states[p.status]||'未连接'}${p.proactive===false?' · 不支持主动通知':''}`,p.id));
 select.value=selected||(platforms.length===1?platforms[0].id:'');updateSave();
}
function reset(){editing=null;preserveLegacy=false;$('form').reset();$('module').disabled=false;$('heading').textContent='新建通知通道';$('save').textContent='创建通道';$('cancel').hidden=true;$('number-fields').hidden=false;$('legacy-hint').hidden=true;fillPlatforms();updateCount();}
function updateCount(){const numbers=id=>new Set($(id).value.trim().split(/[\s,，;；]+/).filter(Boolean)).size;const count=numbers('groups')+numbers('users');$('recipient-count').textContent=count?`已填写 ${count} 个接收目标，最多 30 个。`:'群聊和私聊可同时填写，合计最多 30 个接收目标。';}
function beginEdit(c){
 editing=c;preserveLegacy=c.legacy||!platforms.some(p=>p.id===c.platform_id);
 $('heading').textContent='编辑通知通道';$('save').textContent='保存修改';$('cancel').hidden=false;
 $('name').value=c.name;$('module').value=c.module;$('module').disabled=true;$('enabled').checked=c.enabled;
 $('number-fields').hidden=preserveLegacy;$('legacy-hint').hidden=!preserveLegacy;
 $('groups').value=(c.group_ids||[]).join('\n');$('users').value=(c.user_ids||[]).join('\n');
 fillPlatforms(c.platform_id);updateCount();updateSave();$('form').scrollIntoView({behavior:'smooth',block:'start'});
}
async function copy(url,field){try{await navigator.clipboard.writeText(url);message('API 已复制，可以粘贴到 APP 或 Web。');}catch{field.focus();field.select();if(document.execCommand('copy'))message('API 已复制');else message('浏览器限制了剪贴板，请复制已选中的 API 地址。');}}
async function load(){
 const data=await bridge.apiGet('channels');platforms=data.platforms||[];
 if(!editing)fillPlatforms();else if(!preserveLegacy)fillPlatforms(editing.platform_id);
 $('modules').replaceChildren();
 for(const [key,value] of Object.entries(data.modules)){
  const card=element('div',undefined,'module');card.append(element('strong',`${labels[key]} · ${value.implemented?(value.available?'可用':'加载失败'):'待拓展'}`),element('span',`待发送 ${value.pending} · 失败 ${value.failed}`));
  if(value.error)card.append(element('small',value.error));$('modules').append(card);
 }
 if(!data.public_base_url)message('请先在插件配置中填写通知接口外部地址，再复制 API。',true);
 $('channels').replaceChildren();$('channel-count').textContent=`${data.channels.length} 个通道`;
 if(!data.channels.length)$('channels').append(element('div','还没有通知通道，填写上方表单即可创建。','card empty'));
 for(const c of data.channels){
  const section=element('section',undefined,'card'),heading=element('div',undefined,'channel-heading');
  heading.append(element('h2',c.name),element('span',`${labels[c.module]} · ${c.enabled?'已启用':'已关闭'}`,'badge'));section.append(heading);
  const bot=platforms.find(p=>p.id===c.platform_id);section.append(element('p',bot?`发送机器人：${bot.label}`:'原有接收设置已保留','hint'));
  const targets=element('div',undefined,'destinations');
  for(const number of c.group_ids||[])targets.append(element('span',`群聊 ${number}`,'destination'));
  for(const number of c.user_ids||[])targets.append(element('span',`私聊 ${number}`,'destination'));
  if(c.legacy)targets.append(element('span',`${c.targets.length} 个原有接收目标`,'destination'));section.append(targets);
  const row=element('div',undefined,'api-row'),api=element('input');api.readOnly=true;api.value=c.url;api.setAttribute('aria-label',`${c.name} API 地址`);
  const cp=button('复制 API',()=>copy(c.url,api),'primary');cp.disabled=!c.url;row.append(api,cp);section.append(row);
  const actions=element('div',undefined,'actions');actions.append(button('编辑',()=>beginEdit(c)));
  actions.append(button(c.enabled?'关闭通道':'启用通道',async()=>{if(!c.enabled&&bot?.proactive===false){message('该适配器不支持主动通知',true);return;}await bridge.apiPost('channels/save',{id:c.id,name:c.name,module:c.module,targets:c.targets,enabled:!c.enabled});await load();}));
  actions.append(button('重置 API',async()=>{if(!confirm('重置后旧地址立即失效，确定继续？'))return;await bridge.apiPost('channels/rotate',{id:c.id});await load();message('API 已重置，请重新复制到客户端。');}));
  actions.append(button('删除',async()=>{if(!confirm('删除此通道及待发送通知？'))return;await bridge.apiPost('channels/delete',{id:c.id});if(editing?.id===c.id)reset();await load();},'danger'));
  section.append(actions);$('channels').append(section);
 }
}
$('form').onsubmit=async event=>{
 event.preventDefault();busy=true;updateSave();
 try{
  const payload={name:$('name').value,module:$('module').value,enabled:$('enabled').checked};
  if(editing)payload.id=editing.id;
  if(preserveLegacy)payload.targets=editing.targets;
  else Object.assign(payload,{platform_id:$('platform').value,group_ids:$('groups').value,user_ids:$('users').value});
  await bridge.apiPost('channels/save',payload);reset();await load();message('通道已保存，复制 API 即可连接客户端。');
 }catch(e){message(e.message,true);}finally{busy=false;updateSave();}
};
$('platform').onchange=updateSave;$('groups').oninput=updateCount;$('users').oninput=updateCount;
$('module').onchange=()=>{$('enabled').checked=$('module').value==='checkin';updateSave();};
$('cancel').onclick=reset;$('refresh').onclick=async()=>{try{await load();message('列表已刷新');}catch(e){message(e.message,true);}};
try{await bridge.ready();await load();}catch(e){message(e.message||'加载失败，请刷新后重试',true);}
