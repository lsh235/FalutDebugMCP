"""Standalone service-flow viewer; dynamic labels use textContent."""
import json


def render_html(model: dict, *, language: str = "ko") -> str:
    if language not in {"en", "ko"}:
        raise ValueError("language must be en or ko")
    data = json.dumps(model, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = HTML
    if language == "en":
        template = template.replace('lang="ko"', 'lang="en"')
        for source, translated in ENGLISH.items():
            template = template.replace(source, translated)
    # Translate UI before inserting captured data: evidence stays verbatim.
    return template.replace("__REPORT_DATA__", data)


ENGLISH = {
    "쇼핑몰 서비스 장애 보고서": "Shopping service fault report",
    "서비스 장애 보고서": "Service fault report",
    "실제 호출 행 또는 서비스 노드를 선택하세요.": "Select a recorded call or a service node.",
    "시작 시각 순서입니다. 인과 관계는 전달된 parent RPC ID로 표시합니다. 같은 trace ID만으로 인과 관계를 만들지 않습니다.": "Sorted by local start time. Propagated parent RPC IDs show call ancestry; a shared trace ID alone does not establish causality.",
    "실패 이유는 애플리케이션이 기록한 설명입니다. native RPC 및 crash와 대조하며, 주입 설정만으로 원인을 확정하지 않습니다.": "Failure reasons are application-recorded explanations, corroborated with native RPC and crash evidence. Injection settings alone do not establish the cause.",
    "Python 호출 스택은 수집하지 않습니다. C++ 경계 모듈의 native 함수와 crash 주소만 소스·Build ID로 해석합니다.": "Python stacks are not captured. Native functions and crash addresses belong to the instrumented C++ boundary module and are resolved against source and Build IDs.",
    "호출자가 timeout을 기록한 뒤 수신자가 응답할 수 있습니다. 호출자와 수신자 상태를 구분합니다.": "A receiver may respond after a caller times out. Caller and receiver outcomes remain separate.",
    "SHA-256은 증거 파일을 식별합니다. 로그의 진위나 모든 사건의 완전성을 보증하지 않습니다.": "SHA-256 identifies evidence files; it does not authenticate logs or guarantee complete capture.",
    "저장된 캡처와 로그에서 생성된 독립 HTML입니다. 외부 스크립트·이미지·CDN을 사용하지 않습니다.": "Standalone HTML generated from saved captures and logs, without external scripts, images or CDNs.",
    "이 요청에서 관측된 원인 이벤트 없음. 실제 응답 상태와 주문 결과를 확인하세요.": "No cause event observed for this request. Inspect response status and order outcome.",
    "화살표 = native RPC 양쪽 끝점 관측": "Arrows = observed native RPC endpoints",
    "빨간 노드 = 원인 이벤트 · 점선 노드 = native crash": "Red node = cause event; dashed node = native crash",
    "어디서, 왜 실패했는가": "Where and why did it fail?",
    "증거의 범위와 미확인 항목": "Evidence scope and unresolved items",
    "증거 파일과 SHA-256": "Evidence files and SHA-256",
    "문서 보고서 (Markdown)": "Document report (Markdown)",
    "전체 증거 (JSON)": "Full evidence (JSON)",
    "선택한 RPC의 증거": "Selected RPC evidence",
    "실제 프로세스 간 흐름": "Observed cross-process flow",
    "쇼핑몰 서비스의 관측된 RPC 연결": "Observed shopping-service RPC connections",
    "실제 호출 순서": "Recorded calls",
    "개 프로세스 · ": " processes · ",
    "개 원인 이벤트 · ": " cause events · ",
    "전체 프로세스 ": "All processes: ",
    "개와 고유 식별자": " and unique identities",
    "미확인 / 누락 증거 ": "Unresolved / missing evidence: ",
    " native crash 위치와 소스 보기": " native crash location and source",
    " · 검증된 소스": " · verified source",
    " · 독립 프로세스": " · independent process",
    " 서비스 증거": " service evidence",
    "실패 응답 / 전파": "Failure response / propagation",
    "상태 미확인": "Unknown status",
    "응답 성공": "Successful response",
    "서비스 구간": "Service edge",
    "요청 경로": "Request path",
    "시간 ms": "Time (ms)",
    "밝은 테마": "Light theme",
    "어두운 테마": "Dark theme",
    "인쇄 / PDF": "Print / PDF",
    "요청": "Request",
    "미확인": "Unknown",
    "개 RPC": " RPCs",
    "개 crash": " crashes",
    "개": "",
}


HTML = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FaultDebug · 서비스 장애 보고서</title><link rel="icon" href="data:,"><style>
:root{color-scheme:dark;--bg:#0d1624;--panel:#162438;--ink:#e6edf7;--muted:#9fb2ca;--line:#344962;--ok:#65cfa5;--warn:#ffba69;--bad:#ff777e;--blue:#80b6ff}body.light{color-scheme:light;--bg:#f3f6fa;--panel:#fff;--ink:#172943;--muted:#516682;--line:#bdcbdc;--ok:#187255;--warn:#8b510e;--bad:#b62439;--blue:#2467b5}*{box-sizing:border-box}body{margin:0;font:15px system-ui,sans-serif;background:var(--bg);color:var(--ink)}main{max-width:1550px;margin:auto;padding:28px 36px}header{display:flex;justify-content:space-between;align-items:center;gap:24px}h1{font-size:30px;margin:8px 0 10px}h2{font-size:19px;margin:0 0 16px}p{line-height:1.65;color:var(--muted)}small{color:var(--muted)}button,select{font:inherit;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:7px;padding:9px 13px;cursor:pointer}:focus-visible{outline:3px solid var(--blue)}.bar{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin:20px 0}.badge{padding:7px 12px;border:1px solid var(--line);border-radius:20px;font-size:13px}.bad{color:var(--bad)}.ok{color:var(--ok)}.warn{color:var(--warn)}.panel{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:22px;margin:20px 0}.flow{padding:8px 8px 0}svg{width:100%;height:auto;display:block}svg text{font-family:system-ui,sans-serif}.node rect{fill:var(--panel);stroke:var(--line);stroke-width:1.5}.node text{fill:var(--ink)}.node.root rect{stroke:var(--bad);stroke-width:3}.node.crashed rect{stroke-dasharray:6 4}.edge{fill:none;stroke:var(--ok);stroke-width:2.2}.edge.failed{stroke:var(--bad);stroke-width:3}.edge.unresolved{stroke:var(--warn);stroke-dasharray:5 4}.edge-label{fill:var(--ink);font-size:12px;paint-order:stroke;stroke:var(--panel);stroke-width:6;stroke-linejoin:round}.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.cause{border-left:4px solid var(--bad);padding:4px 0 4px 16px;margin:22px 0}.cause h3{font-size:16px;margin:0 0 8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.65 ui-monospace,monospace;border:1px solid var(--line);padding:12px;border-radius:8px}table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;padding:11px 8px;border-bottom:1px solid var(--line)}tbody tr{cursor:pointer}tbody tr:hover,tbody tr.selected{background:color-mix(in srgb,var(--blue) 12%,transparent)}code{font-size:12px;overflow-wrap:anywhere}a{color:var(--blue)}.limits li{line-height:1.7;color:var(--muted)}details{margin:14px 0}summary{cursor:pointer;color:var(--blue)}.source-active{color:var(--bad);font-weight:bold}.legend{display:flex;gap:18px;flex-wrap:wrap;padding:6px 16px 14px;font-size:12px;color:var(--muted)}.legend span:before{content:'━ ';color:var(--ok)}.legend .error:before{color:var(--bad)}.legend .unknown:before{color:var(--warn)}footer{color:var(--muted);font-size:12px;padding:12px 0 25px}@media(max-width:850px){main{padding:20px 14px}.detail-grid{grid-template-columns:1fr}header{align-items:start}h1{font-size:24px}.table-wrap{overflow-x:auto}}@media print{body{--bg:#fff;--panel:#fff;--ink:#14273e;--muted:#52667c;--line:#ccc;--bad:#b62439;--ok:#187255;--blue:#17578f;color-scheme:light}main{max-width:none;padding:0}.bar,header button{display:none}.panel{break-inside:avoid}.detail-grid{display:block}table{font-size:11px}svg{max-height:350px}.cause{break-inside:avoid}}
</style></head><body><main><header><div><small>FAULTDEBUG / OBSERVED CROSS-SERVICE FLOW</small><h1>쇼핑몰 서비스 장애 보고서</h1><small id="session"></small></div><div><button id="theme">밝은 테마</button> <button id="print">인쇄 / PDF</button></div></header><div class="bar"><span id="counts" class="badge"></span><span id="failures" class="badge"></span><label for="request">요청</label><select id="request"></select><span class="badge">화살표 = native RPC 양쪽 끝점 관측</span></div><section class="panel flow" aria-label="실제 프로세스 간 흐름"><svg id="flow" role="img" aria-label="쇼핑몰 서비스의 관측된 RPC 연결"></svg><div class="legend"><span>응답 성공</span><span class="error">실패 응답 / 전파</span><span class="unknown">상태 미확인</span><span>빨간 노드 = 원인 이벤트 · 점선 노드 = native crash</span></div></section><div class="detail-grid"><section class="panel"><h2>어디서, 왜 실패했는가</h2><div id="causes"></div></section><section class="panel"><h2>선택한 RPC의 증거</h2><p id="selection">실제 호출 행 또는 서비스 노드를 선택하세요.</p><pre id="call-detail"></pre><div id="crash-links"></div></section></div><section class="panel"><h2>실제 호출 순서</h2><p>시작 시각 순서입니다. 인과 관계는 전달된 parent RPC ID로 표시합니다. 같은 trace ID만으로 인과 관계를 만들지 않습니다.</p><div class="table-wrap"><table><thead><tr><th>서비스 구간</th><th>요청 경로</th><th>HTTP</th><th>시간 ms</th><th>RPC → parent</th></tr></thead><tbody id="calls"></tbody></table></div></section><section class="panel"><h2>증거의 범위와 미확인 항목</h2><ul class="limits"><li>실패 이유는 애플리케이션이 기록한 설명입니다. native RPC 및 crash와 대조하며, 주입 설정만으로 원인을 확정하지 않습니다.</li><li>Python 호출 스택은 수집하지 않습니다. C++ 경계 모듈의 native 함수와 crash 주소만 소스·Build ID로 해석합니다.</li><li>호출자가 timeout을 기록한 뒤 수신자가 응답할 수 있습니다. 호출자와 수신자 상태를 구분합니다.</li><li>SHA-256은 증거 파일을 식별합니다. 로그의 진위나 모든 사건의 완전성을 보증하지 않습니다.</li></ul><details><summary id="gaps-label"></summary><pre id="gaps"></pre></details><details><summary>증거 파일과 SHA-256</summary><pre id="evidence"></pre></details><p><a href="report.md">문서 보고서 (Markdown)</a> · <a href="report.json">전체 증거 (JSON)</a></p></section><footer>저장된 캡처와 로그에서 생성된 독립 HTML입니다. 외부 스크립트·이미지·CDN을 사용하지 않습니다.</footer></main><script id="data" type="application/json">__REPORT_DATA__</script><script>
const model=JSON.parse(document.querySelector('#data').textContent),$=s=>document.querySelector(s),ns='http://www.w3.org/2000/svg';
function element(tag,text,className){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el}
function svgEl(tag,attrs,parent){const el=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);parent.append(el);return el}
$('#session').textContent=model.session_id;$('#counts').textContent=model.services.length+'개 프로세스 · '+model.calls.length+'개 RPC';$('#failures').textContent=model.causes.length+'개 원인 이벤트 · '+model.services.filter(s=>s.crashes).length+'개 crash';
const requests=[...new Set(model.calls.map(c=>c.request_id))].sort();for(const request of requests)$('#request').append(element('option',request));const inventory=element('details');inventory.append(element('summary','전체 프로세스 '+model.services.length+'개와 고유 식별자'));inventory.append(element('pre',model.services.map(s=>s.role+' · PID '+s.pid+' · '+s.process_id+' · generation '+s.generation).join('\n')));$('#gaps-label').parentElement.before(inventory);$('#gaps-label').textContent='미확인 / 누락 증거 '+model.unresolved.length+'개';$('#gaps').textContent=JSON.stringify(model.unresolved,null,2);$('#evidence').textContent=model.evidence_files.map(e=>e.path+'\n'+e.kind+'\nSHA-256 '+e.sha256).join('\n\n');
const known={gateway:[30,185],cart:[240,185],checkout:[450,185],inventory:[450,30],payment:[680,185],shipping:[910,185],notification:[1140,185],catalog:[240,350]};
function draw(calls,causes){const svg=$('#flow');svg.replaceChildren();const extra=model.services.filter(s=>!known[s.role]),poolName=extra.every(s=>s.role.startsWith('risk-'))?'risk pool':'other services',positions={...known,[poolName]:[680,350]},displayServices=model.services.filter(s=>known[s.role]);if(extra.length)displayServices.push({role:poolName,pid:'—',rpc_events:extra.reduce((sum,s)=>sum+s.rpc_events,0),crashes:extra.reduce((sum,s)=>sum+s.crashes,0),workers:extra});const height=470;svg.setAttribute('viewBox','0 0 1380 '+height);const defs=svgEl('defs',{},svg);['ok','bad','warn'].forEach(color=>{const marker=svgEl('marker',{id:'arrow-'+color,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'},defs);svgEl('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'var(--'+color+')'},marker)});
const groups=new Map;for(const call of calls){const key=(known[call.from_service]?call.from_service:poolName)+'|'+(known[call.to_service]?call.to_service:poolName);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(call)}
for(const group of groups.values()){const c=group[0],a=positions[known[c.from_service]?c.from_service:poolName],b=positions[known[c.to_service]?c.to_service:poolName];if(!a||!b)continue;const failed=group.some(e=>e.status>=400),unknown=group.some(e=>e.status===undefined),color=failed?'bad':unknown?'warn':'ok';let x1=a[0]+170,y1=a[1]+38,x2=b[0],y2=b[1]+38,path,labelX,labelY;
if(c.from_service==='gateway'&&c.to_service==='checkout'){x1=a[0]+85;y1=a[1];x2=b[0]+35;y2=b[1];path=`M${x1},${y1} V135 H${x2} V${y2}`;labelX=285;labelY=123}
else if(c.from_service==='checkout'&&['shipping','notification'].includes(c.to_service)){x1=a[0]+(c.to_service==='shipping'?120:145);y1=a[1];x2=b[0]+85;y2=b[1];const rail=c.to_service==='shipping'?160:125;path=`M${x1},${y1} V${rail} H${x2} V${y2}`;labelX=(x1+x2)/2;labelY=rail-12}
else if(a[1]===b[1]){path=`M${x1},${y1} C${x1+25},${y1} ${x2-25},${y2} ${x2},${y2}`;labelX=(x1+x2)/2;labelY=y1-12}
else if(a[0]===b[0]){x1=a[0]+85;y1=a[1]+(b[1]>a[1]?76:0);x2=b[0]+85;y2=b[1]+(b[1]>a[1]?0:76);path=`M${x1},${y1} L${x2},${y2}`;labelX=x1+37;labelY=(y1+y2)/2}
else{x1=a[0]+60;y1=a[1]+76;x2=b[0];y2=b[1]+38;path=`M${x1},${y1} C${x1},${y2} ${x2-35},${y2} ${x2},${y2}`;labelX=x1+15;labelY=y2-12}
svgEl('path',{d:path,'data-from':known[c.from_service]?c.from_service:poolName,'data-to':known[c.to_service]?c.to_service:poolName,class:'edge '+(failed?'failed':unknown?'unresolved':''),'marker-end':'url(#arrow-'+color+')'},svg);const text=svgEl('text',{x:labelX,y:labelY,'text-anchor':'middle',class:'edge-label'},svg);text.textContent=group.length+' × '+[...new Set(group.map(e=>e.status??'?'))].join('/');}
for(const service of displayServices){const pos=positions[service.role];if(!pos)continue;const root=causes.some(c=>(c.service===service.role||service.workers?.some(w=>w.role===c.service))&&c.assessment.startsWith('corroborated'));const g=svgEl('g',{'data-service':service.role,class:'node'+(root?' root':'')+(service.crashes?' crashed':''),tabindex:0,role:'button','aria-label':service.role+' 서비스 증거'},svg);svgEl('rect',{x:pos[0],y:pos[1],width:170,height:76,rx:10},g);let text=svgEl('text',{x:pos[0]+14,y:pos[1]+29,'font-size':17,'font-weight':600},g);text.textContent=service.workers?poolName+' × '+service.workers.length:service.role;text=svgEl('text',{x:pos[0]+14,y:pos[1]+53,'font-size':11},g);text.textContent='PID '+service.pid+' · RPC '+service.rpc_events+(service.crashes?' · CRASH':'');g.onclick=()=>{$('#selection').textContent=service.role+' · 독립 프로세스';$('#call-detail').textContent=JSON.stringify(service.workers??service,null,2)};g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();g.onclick()}};}}
function show(){const request=$('#request').value,calls=model.calls.filter(c=>c.request_id===request),causes=model.causes.filter(c=>c.request_id===request);draw(calls,causes);$('#causes').replaceChildren();if(!causes.length)$('#causes').append(element('p','이 요청에서 관측된 원인 이벤트 없음. 실제 응답 상태와 주문 결과를 확인하세요.'));
for(const cause of causes){const card=element('div',undefined,'cause');card.append(element('h3',cause.service+' / '+cause.code));card.append(element('p',cause.reason));card.append(element('small',cause.assessment+' · RPC '+cause.rpc_id));if(cause.source){const details=element('details');details.append(element('summary',cause.source.file+':'+cause.source.line+' · 검증된 소스'));const pre=element('pre');for(const line of cause.source.lines)pre.append(element('span',line.line+'  '+line.text+'\n',line.line===cause.source.line?'source-active':''));details.append(pre);card.append(details)}$('#causes').append(card)}
$('#calls').replaceChildren();for(const call of calls){const row=element('tr');row.tabIndex=0;row.setAttribute('role','button');row.setAttribute('aria-label',call.from_service+' to '+call.to_service+' RPC '+call.rpc_id);row.append(element('td',call.from_service+' → '+call.to_service),element('td',call.path),element('td',call.status??'미확인',call.status>=400?'bad':'ok'),element('td',call.duration_ms??'미확인'),element('td',call.rpc_id+' → '+call.parent_rpc_id));row.onclick=()=>{$('#calls').querySelectorAll('tr').forEach(r=>r.classList.remove('selected'));row.classList.add('selected');$('#selection').textContent=call.from_service+' → '+call.to_service+' · '+call.path;$('#call-detail').textContent=JSON.stringify(call,null,2)};row.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();row.onclick()}};$('#calls').append(row)}
$('#crash-links').replaceChildren();for(const service of model.services.filter(s=>s.fault_report)){const a=element('a',service.role+' native crash 위치와 소스 보기 ↗');a.href=service.fault_report;$('#crash-links').append(a)}$('#call-detail').textContent='';$('#selection').textContent='실제 호출 행 또는 서비스 노드를 선택하세요.';}
$('#request').onchange=show;$('#theme').onclick=()=>{document.body.classList.toggle('light');$('#theme').textContent=document.body.classList.contains('light')?'어두운 테마':'밝은 테마'};$('#print').onclick=()=>window.print();show();
</script></body></html>'''
