"""Standalone report UI; no network assets or rendering dependencies."""
from __future__ import annotations

from html import escape
import json


def render_html(model: dict) -> str:
    ko = model["language"] == "ko"
    labels = {
        "title": "장애 실행 흐름" if ko else "Fault execution flow",
        "subtitle": "관측된 실행 기록에서 장애 위치까지" if ko else "From retained execution records to the captured fault site",
        "thread": "스레드 / 세대" if ko else "Thread / generation",
        "search": "함수·주소 검색" if ko else "Search function or address",
        "context": "장애 주변" if ko else "Fault context",
        "all": "보고서의 전체 기록" if ko else "All report events",
        "theme": "테마 전환" if ko else "Toggle theme",
        "print": "문서 인쇄 / PDF" if ko else "Print document / PDF",
        "details": "선택한 기록의 근거" if ko else "Selected record evidence",
        "record": "기록 순서" if ko else "Record order",
        "nesting": "계측된 호출 중첩" if ko else "Instrumented nesting",
        "crash": "장애 PC" if ko else "Captured fault PC",
        "gap": "누락·미확인" if ko else "Missing / unknown",
        "boundary": "화살표는 관측 순서·호출 중첩입니다. 장애 원인을 단정하지 않습니다." if ko else "Arrows show observed order and instrumented nesting. They do not prove the root cause.",
        "limits": "기록 한계" if ko else "Evidence limits",
        "source": "검증된 소스" if ko else "Verified source",
        "static": "정적 후보 — 실행 증거와 별도" if ko else "Static candidates — separate from runtime evidence",
        "none": "선택 가능한 기록이 없습니다." if ko else "No retained event is available.",
    }
    # Never insert artifact text into executable JavaScript or HTML markup.
    def js_safe(value):
        if isinstance(value, dict):
            return {key: js_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [js_safe(item) for item in value]
        if type(value) is int and abs(value) > (1 << 53) - 1:
            return str(value)
        return value
    payload = json.dumps(js_safe({"model": model, "labels": labels}), ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    printable = [f"<h1>{escape(labels['title'])}</h1>", f"<p>{escape(labels['boundary'])}</p>",
                 f"<p>Evidence: {escape(model['capture']['evidence_status'])}</p>",
                 f"<p>Artifact SHA256: <code>{escape(model.get('artifact', {}).get('sha256', ''))}</code></p>"]
    for c in model["crashes"]:
        pc = hex(c['pc']) if c['pc'] is not None else 'unrecorded'
        address = hex(c['fault_address']) if c['fault_address'] is not None else 'unrecorded'
        printable.append(f"<h2>{escape(c['signal_name'])} · TID {c['tid']} / {c['generation']}</h2><p>PC: {pc} · {escape(c['label'])}<br>Fault address: {address}<br>Last event (temporal context): {escape(str(c['last_event']))}</p>")
    for t in model["threads"]:
        printable.append(f"<h2>TID {t['tid']} / generation {t['generation']}</h2><p>Retained: {t['retained_events']}; omitted from report: {t['omitted_from_view']}; dropped: {t['dropped_count']}</p><table><thead><tr><th>Seq</th><th>Event</th><th>Function</th><th>Gap</th></tr></thead><tbody>")
        for e in t["events"]:
            printable.append(f"<tr><td>{e['sequence']}</td><td>{escape(e['kind'])}</td><td>{escape(e['label'])}</td><td>{escape(', '.join(e['gaps_before']))}</td></tr>")
        printable.append("</tbody></table>")
    printable.append(f"<h2>{escape(labels['limits'])}</h2><ul>")
    printable.extend(f"<li>{escape(json.dumps(g, ensure_ascii=False))}</li>" for g in model["gaps"])
    printable.extend(f"<li>{escape(d['code'] + ': ' + d['message'])}</li>" for d in model["diagnostics"])
    printable.extend(f"<li>{escape(line)}</li>" for line in model["limitations"])
    printable.append("</ul>")
    for fid, source in model["sources"].items():
        printable.append(f"<section class=\"print-source\"><h2>{escape(labels['source'])} · {escape(fid)}</h2><p>{escape(str(source.get('file')))}:{source.get('start_line')}–{source.get('display_end_line')}</p><pre>{escape(source.get('source', ''))}</pre></section>")
    document = TEMPLATE.replace("__LANG__", model["language"]).replace("__TITLE__", escape(labels["title"]))
    return document.replace("__PRINT_DOCUMENT__", "\n".join(printable)).replace("__PAYLOAD__", payload)


TEMPLATE = r'''<!doctype html>
<html lang="__LANG__"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>__TITLE__ · FaultDebug</title><style>
:root{color-scheme:dark;--bg:#0c1422;--panel:#131f30;--card:#1b2b40;--ink:#edf4ff;--muted:#a5b6cb;--line:#34485f;--cyan:#70ded5;--red:#ff899c;--amber:#ffd17b;--shadow:0 16px 60px #0003}
:root.light{color-scheme:light;--bg:#eef3f8;--panel:#fff;--card:#f4f8fc;--ink:#182c42;--muted:#536a81;--line:#c1cedb;--cyan:#087c76;--red:#bb2549;--amber:#8a5900;--shadow:0 16px 60px #19304a0b}
*{box-sizing:border-box}body{margin:0;overflow-wrap:anywhere;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,sans-serif}header,main,footer{max-width:1640px;margin:auto;padding:24px 32px}header{border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:24px}.brand{color:var(--cyan);font-size:12px;font-weight:750;letter-spacing:.2em}h1{font-size:30px;letter-spacing:-.03em;margin:7px 0}h2{font-size:17px;margin:0 0 16px}p{margin:6px 0;color:var(--muted)}button,select,input{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 12px}button{cursor:pointer}button:hover,button:focus-visible{border-color:var(--cyan)}button.active{background:var(--cyan);color:var(--bg)}.actions,.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-bottom:20px}.stat,.panel{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow)}.stat{padding:18px 22px}.stat strong{overflow-wrap:anywhere;display:block;font-size:22px;margin-top:6px}.eyebrow{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.09em}.danger{color:var(--red)}.warning{color:var(--amber)}.toolbar{margin-bottom:16px}.toolbar input{flex:1;min-width:200px}select{max-width:320px}.workspace{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:20px}.flowhead{padding:20px 22px;border-bottom:1px solid var(--line)}.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted)}.legend i{display:inline-block;width:14px;height:3px;margin:0 6px 3px 0;background:var(--line)}.legend .cyan{background:var(--cyan)}.legend .red{background:var(--red)}.legend .amber{background:var(--amber)}.viewport{overflow:auto;max-height:clamp(320px,calc(100vh - 540px),680px);padding:18px 12px;scrollbar-color:var(--line) var(--panel)}svg{display:block;width:100%;min-width:640px}.node{cursor:pointer;outline:none}.node rect{fill:var(--card);stroke:var(--line);stroke-width:1.2}.node:hover rect,.node:focus rect,.node.selected rect{stroke:var(--cyan);stroke-width:2}.node text{fill:var(--ink);font-family:system-ui,sans-serif}.node .sub{fill:var(--muted);font-size:12px}.node .name{font-size:16px;font-weight:650}.node.crash rect{stroke:var(--red)}.node.crash .name{fill:var(--red)}.node.gap rect{stroke:var(--amber)}.node.dim{opacity:.25}.edge{fill:none;stroke:var(--line);stroke-width:1.5;stroke-dasharray:4 5}.edge.nesting{stroke:var(--cyan);stroke-dasharray:none;opacity:.65}.edge.context{stroke:var(--red);stroke-dasharray:4 5}.gaptext{fill:var(--amber);font:12px system-ui,sans-serif}.detail{padding:22px;align-self:start;max-height:clamp(420px,calc(100vh - 380px),820px);overflow:auto;overflow-wrap:anywhere}.detail h3{margin:8px 0;font-size:18px}.badge{display:inline-block;border:1px solid var(--line);border-radius:5px;padding:2px 7px;font-size:12px;margin:0 6px 8px 0;color:var(--cyan)}dl{margin:12px 0}dt{font-size:12px;color:var(--muted);margin-top:9px}dd{margin:1px 0;font-family:ui-monospace,monospace;font-size:13px;white-space:pre-wrap}pre{font:12px/1.65 ui-monospace,monospace;background:var(--bg);border-radius:8px;padding:14px;overflow:auto;white-space:pre-wrap;word-break:break-word}.limits{margin-top:20px;padding:22px}.limits summary{cursor:pointer;color:var(--amber)}li{margin:8px 0;color:var(--muted)}footer{font-size:12px;color:var(--muted)}.print-document{display:none}.boundary{padding:12px 22px;background:var(--card);border-radius:0 0 16px 16px;font-size:12px;color:var(--muted)}
@media(max-width:1000px){.workspace{grid-template-columns:minmax(0,1fr)}.detail{max-height:none}.stats{gap:8px}.stat{padding:12px}header,main,footer{padding:18px}header{align-items:start;flex-direction:column}h1{font-size:25px}}
@media print{header,main,footer{display:none}.print-document{display:block;color:#172536;padding:0 8mm;font:11pt/1.5 system-ui,sans-serif}.print-document h1{font-size:24pt}.print-document h2{font-size:13pt;margin-top:16px;break-after:avoid;overflow-wrap:anywhere}.print-source{break-inside:avoid}.print-document table{border-collapse:collapse;width:100%;font-size:9pt;table-layout:fixed}.print-document th,.print-document td{border:1px solid #ccd3dc;text-align:left;padding:5px;overflow-wrap:anywhere}.print-document th:first-child{width:9%}.print-document th:nth-child(2){width:12%}.print-document tr{break-inside:avoid}.print-document pre{background:#f4f6f8;font-size:8pt}.print-document p,.print-document li{color:#344558}body{background:white}}
</style></head><body>
<header><div><div class="brand">FAULTDEBUG / EVIDENCE REPORT</div><h1 id="title"></h1><p id="subtitle"></p></div><div class="actions"><button id="theme"></button><button id="print"></button></div></header>
<main><section class="stats" aria-label="Capture summary"><div class="stat"><div class="eyebrow" id="faultLabel"></div><strong class="danger" id="faultStat"></strong></div><div class="stat"><div class="eyebrow">Evidence</div><strong id="evidenceStat"></strong></div><div class="stat"><div class="eyebrow" id="threadLabel"></div><strong id="threadStat"></strong></div></section>
<div class="toolbar"><label for="thread" id="threadSelectLabel"></label><select id="thread"></select><input id="search" type="search"><button id="context" class="active"></button><button id="all"></button></div>
<div class="workspace"><section class="panel"><div class="flowhead"><h2 id="flowTitle"></h2><p id="count"></p><div class="legend"><span><i></i><span id="recordLegend"></span></span><span><i class="cyan"></i><span id="nestLegend"></span></span><span><i class="red"></i><span id="crashLegend"></span></span><span><i class="amber"></i><span id="gapLegend"></span></span></div></div><div class="viewport"><svg id="flow" role="group" aria-label="Recorded runtime flow"></svg></div><div class="boundary" id="boundary"></div></section><aside class="panel detail" id="detail" aria-live="polite"></aside></div>
<details class="panel limits"><summary id="limitTitle"></summary><ul id="limits"></ul><h2>Diagnostics</h2><ul id="diagnostics"></ul></details>
<noscript><p>JavaScript is required for interactive flow. The full report is available in report.md and report.json.</p></noscript></main>
<footer id="provenance"></footer><article class="print-document">__PRINT_DOCUMENT__</article>
<script id="report-data" type="application/json">__PAYLOAD__</script><script>
'use strict';
const {model:M,labels:L}=JSON.parse(document.getElementById('report-data').textContent);
const $=id=>document.getElementById(id), NS='http://www.w3.org/2000/svg';
const set=(id,value)=>{$(id).textContent=value};
for(const [id,key] of Object.entries({title:'title',subtitle:'subtitle',theme:'theme',print:'print',context:'context',all:'all',faultLabel:'crash',threadLabel:'thread',threadSelectLabel:'thread',recordLegend:'record',nestLegend:'nesting',crashLegend:'crash',gapLegend:'gap',boundary:'boundary',limitTitle:'limits'}))set(id,L[key]);
$('search').placeholder=L.search;$('search').setAttribute('aria-label',L.search);
set('faultStat',M.crashes.map(c=>c.signal_name).join(', ')||'No crash record');set('evidenceStat',M.capture.evidence_status);set('threadStat',M.threads.length);
if(M.capture.evidence_status==='limited')$('evidenceStat').className='warning';
set('provenance','FDAR SHA256 '+(M.artifact?.sha256||'unavailable')+' · Offline report · FaultDebug');
const addList=(parent,text)=>{const li=document.createElement('li');li.textContent=text;parent.appendChild(li)};
M.gaps.forEach(g=>addList($('limits'),JSON.stringify(g)));M.limitations.forEach(s=>addList($('limits'),s));M.diagnostics.forEach(d=>addList($('diagnostics'),d.code+': '+d.message));
for(const t of M.threads){const o=document.createElement('option');o.value=t.id;o.textContent='TID '+t.tid+' / generation '+t.generation+(M.crashes.some(c=>c.thread===t.id)?' · '+L.crash:'');$('thread').appendChild(o)}
const orphan=M.crashes.filter(c=>!c.thread);if(orphan.length){const o=document.createElement('option');o.value='unmatched';o.textContent=L.crash+' / thread unresolved';$('thread').appendChild(o)}
let selected=M.crashes[0]?.id||M.threads[0]?.events.at(-1)?.id, context=true, displayed=[];
if(M.crashes[0])$('thread').value=M.crashes[0].thread||'unmatched';
const hex=a=>a==null?'unrecorded':'0x'+BigInt(a).toString(16);
function svg(tag,attrs,parent,text){const el=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);if(text!==undefined)el.textContent=text;parent.appendChild(el);return el}
function details(node){const root=$('detail');root.replaceChildren();const heading=document.createElement('h2');heading.textContent=L.details;root.appendChild(heading);if(!node){root.appendChild(document.createTextNode(L.none));return}const h=document.createElement('h3');h.textContent=node.label;root.appendChild(h);for(const label of [node.kind,node.source_verified?L.source:(node.resolution.resolved?'Verified binary':'Unresolved')]){const badge=document.createElement('span');badge.className='badge';badge.textContent=label;root.appendChild(badge)}
const dl=document.createElement('dl');root.appendChild(dl);const field=(key,value)=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key;dd.textContent=typeof value==='object'?JSON.stringify(value):String(value??'unrecorded');dl.append(dt,dd)};
field('Record ID',node.id);field('Sequence',node.sequence);field('Monotonic ns',node.monotonic_ns);field(node.kind==='crash'?'PC':'Function address',hex(node.kind==='crash'?node.pc:node.function));if(node.kind==='crash'){field('Fault address',hex(node.fault_address));field('Last event (temporal context)',node.last_event)}else field('Callsite address',hex(node.callsite));field('Resolution',node.resolution.reason||'Build ID verified');field('Module',node.resolution.module===''&&node.resolution.resolved?'main executable':node.resolution.module);field('Build ID',node.resolution.build_id);if(node.resolution.source)field('Debug location',node.resolution.source.file+':'+node.resolution.source.line+':'+node.resolution.source.column);if(node.gaps_before?.length)field('Gaps',node.gaps_before);
const s=M.sources[node.resolution.function_id];if(node.source_verified&&s){field(L.source,s.file+':'+s.start_line+'–'+s.display_end_line);const pre=document.createElement('pre');pre.textContent=s.source.split('\n').map((line,i)=>((s.start_line+i===node.resolution.source?.line)?'→ ':'  ')+(s.start_line+i)+'  '+line).join('\n');const location=document.createElement('p');location.textContent=s.file+':'+s.start_line+'–'+s.display_end_line;location.style.fontSize='12px';root.insertBefore(location,dl);root.insertBefore(pre,dl)}else{const p=document.createElement('p');p.textContent='No verified source snippet. Supply a matching source/binary bundle.';root.appendChild(p)}
const candidates=[...(node.resolution.static_edges||[]),...(node.resolution.static_unresolved_edges||[])];if(candidates.length){const h=document.createElement('h3');h.textContent=L.static;const pre=document.createElement('pre');pre.textContent=JSON.stringify(candidates,null,2);root.append(h,pre)} }
function render(scrollToFault=false){const t=M.threads.find(t=>t.id===$('thread').value);const events=t?.events||[];const contextIds=new Set([...(t?.unmatched_entries||[]).map(e=>e.event_id),...events.slice(-10).map(e=>e.id)]);displayed=context?events.filter(e=>contextIds.has(e.id)):events.slice();const crashes=M.crashes.filter(c=>t?c.thread===t.id:!c.thread);displayed.push(...crashes);set('flowTitle',t?'TID '+t.tid+' / generation '+t.generation:L.crash);set('count',(context?L.context:L.all)+' · '+displayed.length+' nodes · hidden in view '+(events.length-(displayed.length-crashes.length))+' · retained '+(t?.retained_events||0)+' · omitted from report '+(t?.omitted_from_view||0)+' · dropped '+(t?.dropped_count||0));
const root=$('flow');root.replaceChildren();const height=Math.max(180,displayed.length*100+50);root.setAttribute('viewBox','0 0 820 '+height);root.setAttribute('height',height);const defs=svg('defs',{},root);for(const [name,color] of [['order','var(--line)'],['nest','var(--cyan)'],['fault','var(--red)']]){const marker=svg('marker',{id:'arrow-'+name,viewBox:'0 0 10 10',refX:10,refY:5,markerWidth:6,markerHeight:6,orient:'auto'},defs);svg('path',{d:'M 0 0 L 10 5 L 0 10 Z',fill:color},marker)}const positions=new Map();displayed.forEach((n,i)=>positions.set(n.id,{x:100+Math.min(n.depth||0,5)*26,y:24+i*100}));
for(const e of M.edges){const a=positions.get(e.from),b=positions.get(e.to);if(!a||!b)continue;if(e.kind==='observed_nesting'){if(e.from!==selected&&e.to!==selected)continue;const side=Math.min(a.x,b.x)-24;svg('path',{d:`M ${a.x} ${a.y+36} H ${side} V ${b.y+36} H ${b.x}`,class:'edge nesting','marker-end':'url(#arrow-nest)'},root)}else svg('path',{d:`M ${a.x+20} ${a.y+72} V ${b.y-12} H ${b.x+20} V ${b.y}`,class:'edge '+(e.kind==='crash_context'?'context':''),'marker-end':'url(#arrow-'+(e.kind==='crash_context'?'fault':'order')+')'},root)}
const query=$('search').value.toLowerCase();for(const n of displayed){const p=positions.get(n.id),gap=n.gaps_before?.length;const match=!query||(n.label+' '+hex(n.function??n.pc)+' '+n.id).toLowerCase().includes(query);const g=svg('g',{class:'node '+(n.kind==='crash'?'crash ':'')+(gap?'gap ':'')+(n.id===selected?'selected ':'')+(!match?'dim':''),role:'button',tabindex:0,'aria-label':n.kind+' '+n.label,'data-id':n.id},root);svg('title',{},g,n.label);svg('rect',{x:p.x,y:p.y,width:580,height:72,rx:12},g);svg('text',{x:p.x+16,y:p.y+25,class:'name'},g,(n.kind==='crash'?n.signal_name+' · ':'')+(n.label.length>49?n.label.slice(0,46)+'…':n.label));svg('text',{x:p.x+16,y:p.y+51,class:'sub'},g,n.kind==='crash'?'PC '+hex(n.pc)+' · '+L.crash:n.kind.toUpperCase()+' · seq '+n.sequence+' · '+hex(n.function)+(n.source_verified?' · '+L.source:''));if(gap)svg('text',{x:p.x,y:p.y-5,class:'gaptext'},root,L.gap+' · '+n.gaps_before.join(', '));const choose=()=>{selected=n.id;render();root.querySelector('[data-id="'+n.id+'"]').focus({preventScroll:true})};g.addEventListener('click',choose);g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose()}})}
if(!displayed.length)svg('text',{x:30,y:80,class:'gaptext'},root,L.none);details(displayed.find(n=>n.id===selected)||displayed.at(-1));if(scrollToFault&&crashes.length){const viewport=root.parentElement;viewport.scrollTop=viewport.scrollHeight;}}
$('thread').addEventListener('change',()=>{selected=null;render(true)});$('search').addEventListener('input',render);$('context').addEventListener('click',()=>{context=true;$('context').classList.add('active');$('all').classList.remove('active');render(true)});$('all').addEventListener('click',()=>{context=false;$('all').classList.add('active');$('context').classList.remove('active');render()});$('theme').addEventListener('click',()=>document.documentElement.classList.toggle('light'));$('print').addEventListener('click',()=>window.print());render(true);
</script></body></html>'''
