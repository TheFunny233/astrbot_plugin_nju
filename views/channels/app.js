const bridge = window.AstrBotPluginView;
const $ = id => document.getElementById(id);
const labels = {checkin:'签到',course:'抢课',venue:'抢场'};
const states = {running:'运行中',pending:'连接中',stopped:'未连接',disabled:'已停用',error:'连接异常'};
let editing = null, platforms = [], recipients = [], selectedTargets = new Set(), preserveLegacy = false, busy = false;
function message(text, error=false){$('status').textContent=text;$('status').dataset.error=String(error);}
function element(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
function button(text,action,className){const b=element('button',text,className);b.type='button';b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){message(e.message||'操作失败，请重试',true);}finally{b.disabled=false;}};return b;}
function recipientName(r){return r.alias||r.name||`${r.kind==='group'?'未命名群聊':'未命名用户'} · ${r.target.split(':').at(-1).slice(-8)}`;}
function updateSave(){
 const selected=platforms.find(p=>p.id===$('platform').value), unsupported=selected?.proactive===false;
 if(!preserveLegacy&&unsupported)$('enabled').checked=false;
 $('enabled').disabled=busy||(!preserveLegacy&&unsupported);
 $('save').disabled=busy||(!preserveLegacy&&(!selected||!selectedTargets.size||selectedTargets.size>30));
 $('platform-hint').textContent=platforms.length?'选择机器人后，勾选它已记录的群聊和用户。':'还没有可选择的机器人。请先在 AstrBot 的消息平台中添加机器人，再刷新此页。';
 let hint=selected?'仅通知勾选的目标；实际发送仍需具备平台权限和可用额度。':'';
 if(unsupported)hint+=' 该适配器不支持主动通知，通道只能保存为关闭状态。';
 else if(selected?.proactive===null)hint+=' 机器人尚未运行，连接后会重新检查主动通知能力。';
 $('protocol-hint').textContent=hint;
 $('recipient-count').textContent=`已勾选 ${selectedTargets.size} 个接收目标，群聊和私聊合计最多 30 个。`;
}
function renderRecipients(){
 const platform=$('platform').value, query=$('recipient-search').value.trim().toLocaleLowerCase();
 for(const [kind,id] of [['group','group-options'],['user','user-options']]){
  const list=$(id);list.replaceChildren();
  const choices=recipients.filter(r=>r.platform_id===platform&&r.kind===kind&&
   `${recipientName(r)} ${r.name} ${r.target}`.toLocaleLowerCase().includes(query));
  for(const r of choices){
   const row=element('div',undefined,'recipient-row'),label=element('label',undefined,'recipient-choice');
   const check=element('input');check.type='checkbox';check.checked=selectedTargets.has(r.target);check.disabled=busy;
   check.onchange=()=>{if(check.checked)selectedTargets.add(r.target);else selectedTargets.delete(r.target);updateSave();};
   const description=element('span');description.append(element('strong',recipientName(r)));
   const detail=[];
   if(r.alias&&r.name)detail.push(r.name);
   if(r.last_seen)detail.push(`最近互动：${new Date(r.last_seen*1000).toLocaleString()}`);
   else detail.push('原通道接收目标，尚未再次互动');
   description.append(element('small',detail.join(' · ')));label.append(check,description);row.append(label);
   if(r.observed){
    const rename=button('备注',async()=>{
     const alias=prompt('设置接收目标的备注（留空恢复原名称）',r.alias||'');if(alias===null)return;
     await bridge.apiPost('recipients/rename',{target:r.target,alias});await load();message('备注已保存');
    });rename.disabled=busy;rename.setAttribute('aria-label',`为${recipientName(r)}设置备注`);row.append(rename);
   }
   list.append(row);
  }
  if(!choices.length)list.append(element('p',!platform?'请先选择机器人。':query?'没有匹配的目标。':
   kind==='group'?'尚未记录群聊。在目标群里 @机器人发送消息后，点击刷新列表。':'尚未记录用户。让接收人私聊机器人一次后，点击刷新列表。','recipient-empty'));
 }
 updateSave();
}
function fillPlatforms(selected=''){
 const select=$('platform');select.replaceChildren();
 if(platforms.length!==1)select.append(new Option(platforms.length?'请选择发送消息的机器人':'请先添加机器人',''));
 for(const p of platforms)select.append(new Option(`${p.label} · ${p.protocol_label||p.type} · ${states[p.status]||'未连接'}${p.proactive===false?' · 不支持主动通知':''}`,p.id));
 select.value=selected||(platforms.length===1?platforms[0].id:'');renderRecipients();
}
function reset(){
 editing=null;selectedTargets=new Set();preserveLegacy=false;$('form').reset();$('module').disabled=false;
 $('heading').textContent='新建通知通道';$('save').textContent='创建通道';$('cancel').hidden=true;
 $('number-fields').hidden=false;$('legacy-hint').hidden=true;fillPlatforms();
}
function beginEdit(c){
 editing=c;selectedTargets=new Set(c.targets);preserveLegacy=c.legacy||!platforms.some(p=>p.id===c.platform_id);
 $('heading').textContent='编辑通知通道';$('save').textContent='保存修改';$('cancel').hidden=false;
 $('name').value=c.name;$('module').value=c.module;$('module').disabled=true;$('enabled').checked=c.enabled;
 $('recipient-search').value='';$('number-fields').hidden=preserveLegacy;$('legacy-hint').hidden=!preserveLegacy;
 fillPlatforms(c.platform_id);$('form').scrollIntoView({behavior:'smooth',block:'start'});
}
async function copy(url,field){try{await navigator.clipboard.writeText(url);message('API 已复制，可以粘贴到 APP 或 Web。');}catch{field.focus();field.select();if(document.execCommand('copy'))message('API 已复制');else message('浏览器限制了剪贴板，请复制已选中的 API 地址。');}}
async function load(){
 const platform=$('platform').value||editing?.platform_id||'';
 const data=await bridge.apiGet('channels');platforms=data.platforms||[];recipients=data.recipients||[];
 fillPlatforms(platform);
 $('modules').replaceChildren();
 for(const [key,value] of Object.entries(data.modules)){
  const card=element('div',undefined,'module');card.append(element('strong',`${labels[key]} · ${value.implemented?(value.available?'可用':'加载失败'):'待拓展'}`),element('span',`待发送 ${value.pending} · 失败 ${value.failed}`));
  if(value.error)card.append(element('small',value.error));$('modules').append(card);
 }
 if(!data.public_base_url)message('请先在插件配置中填写通知接口外部地址，再复制 API。',true);
 $('channels').replaceChildren();$('channel-count').textContent=`${data.channels.length} 个通道`;
 if(!data.channels.length)$('channels').append(element('div','还没有通知通道，勾选接收目标即可创建。','card empty'));
 for(const c of data.channels){
  const section=element('section',undefined,'card'),heading=element('div',undefined,'channel-heading');
  heading.append(element('h2',c.name),element('span',`${labels[c.module]} · ${c.enabled?'已启用':'已关闭'}`,'badge'));section.append(heading);
  const bot=platforms.find(p=>p.id===c.platform_id);section.append(element('p',bot?`发送机器人：${bot.label}`:'原有接收设置已保留','hint'));
  const targets=element('div',undefined,'destinations');
  for(const target of c.targets){
   const r=recipients.find(item=>item.target===target);
   targets.append(element('span',r?`${r.kind==='group'?'群聊':'私聊'} · ${recipientName(r)}`:'原有接收目标','destination'));
  }
  section.append(targets);
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
 event.preventDefault();busy=true;renderRecipients();
 try{
  const payload={name:$('name').value,module:$('module').value,enabled:$('enabled').checked};
  if(editing)payload.id=editing.id;
  if(preserveLegacy)payload.targets=editing.targets;
  else Object.assign(payload,{platform_id:$('platform').value,recipient_targets:[...selectedTargets]});
  await bridge.apiPost('channels/save',payload);reset();await load();message('通道已保存，复制 API 即可连接客户端。');
 }catch(e){message(e.message,true);}finally{busy=false;renderRecipients();}
};
$('platform').onchange=()=>{selectedTargets=new Set();$('recipient-search').value='';renderRecipients();};
$('recipient-search').oninput=renderRecipients;
$('module').onchange=()=>{$('enabled').checked=['checkin','venue'].includes($('module').value);updateSave();};
$('cancel').onclick=reset;$('refresh').onclick=async()=>{try{await load();message('列表已刷新，已勾选的目标会保留');}catch(e){message(e.message,true);}};
try{await bridge.ready();await load();}catch(e){message(e.message||'加载失败，请刷新后重试',true);}
