from __future__ import annotations

import html
import json
import re
import sqlite3
import sys
import threading
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from . import NOT_LEGAL_ADVICE, ingest
from .case_import import import_case_folder
from .copilot import CopilotError
from .copilot_web import CopilotHub, render_copilot_page
from .crawler import Violation, build_live_sources, collect
from .debate import DebateConflict, DebateHub
from .debate_web import render_practice_page
from .device import frame_to_glasses_payload, frame_to_payload
from .docs import render
from .hud import HudSimulator, TranscriptLine
from .matcher import MatchResult, evaluate
from .pipeline import (
    MIN_AUTO_CONFIDENCE,
    SAMPLE_RECORD,
    SAMPLE_TRANSCRIPT,
    PipelineResult,
    run,
)
from .research import ResearchStore
from .research_web import render_research_page
from .tagger import TagSet, tag_text
from .vocabulary import VocabularyConflict, VocabularyStore
from .vocabulary_web import render_vocabulary_page


def violation_to_json(violation: Violation) -> dict:
    item = asdict(violation)
    item["window_start"] = violation.window_start.isoformat()
    item["window_end"] = violation.window_end.isoformat()
    return item


def match_to_json(match: MatchResult) -> dict:
    v = match.violation
    return {
        "violation_id": v.id,
        "program": v.program,
        "source": v.source,
        "claim_type": match.claim_type,
        "confidence": round(match.confidence, 3),
        "evidence": list(match.evidence),
    }


def simulate_result_json(result: PipelineResult) -> dict:
    case = None
    if result.case is not None:
        case = {
            "case_number": result.case.case_number,
            "cause": result.case.cause,
            "party": result.case.party,
            "stage": result.case.stage,
            "history": [{"day": day, "entry": entry} for day, entry in result.case.history],
        }
    briefing = None
    if result.briefing is not None:
        briefing = {
            "stage": result.briefing.stage,
            "title": result.briefing.title,
            "checklist": list(result.briefing.checklist),
            "caution": result.briefing.caution,
        }
    return {
        "total_violations": result.total_violations,
        "min_auto_confidence": MIN_AUTO_CONFIDENCE,
        "matches": [match_to_json(m) for m in result.matches],
        "review": [match_to_json(m) for m in result.review],
        "case": case,
        "briefing": briefing,
        "tags": result.tags.summary().splitlines() if result.tags is not None else [],
        "drafts": [
            {"violation_id": vid, "doc_type": d.doc_type, "document_id": d.document_id, "text": d.text}
            for vid, d in result.drafts
        ],
        "frames": [frame_to_payload(f) for f in result.frames],
    }


NAV = (
    "<nav><a href=\"/\">Dashboard</a>"
    "<a href=\"/copilot\">Live coach</a>"
    "<a href=\"/practice\">Debate practice</a>"
    "<a href=\"/vocabulary\">Vocabulary</a>"
    "<a href=\"/research\">Research</a>"
    "<a href=\"/documents\">Discovery</a>"
    "<a href=\"/suits\">Class actions</a>"
    "<a href=\"/live\">Collections</a>"
    "<a href=\"/exports\">Exports</a></nav>"
)

DEFAULT_SUIT_QUERY = '"auto renew" class action'


@dataclass
class DocumentRecord:
    doc_id: str
    name: str
    ingested_at: str
    text: str
    tags: TagSet
    links: tuple[str, ...] = ()


def document_to_json(rec: DocumentRecord) -> dict:
    return {
        "doc_id": rec.doc_id,
        "name": rec.name,
        "ingested_at": rec.ingested_at,
        "text": rec.text,
        "tags": rec.tags.to_dict(),
        "links": list(rec.links),
    }


def violation_from_json(item: dict) -> Violation:
    return Violation(
        id=item["id"],
        program=item["program"],
        source=item["source"],
        status=item["status"],
        window_start=date.fromisoformat(item["window_start"]),
        window_end=date.fromisoformat(item["window_end"]),
        claim_type=item["claim_type"],
        rules=tuple(item.get("rules") or ()),
        description=item.get("description", ""),
    )


LINK_RE = re.compile(r"\[\[([^\[\]\n]{1,120})\]\]")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

SAMPLE_DOCS = (
    (
        "Complaint \u2014 Doe v. Voltmax",
        "Plaintiff: Janet A. Doe\nDefendant: Voltmax Direct LLC\n"
        "Filed: 2026-09-12\nDefendant charged a hidden late fee of $30.00 and "
        "faces a class action settlement. See [[Contract p.1]] and "
        "[[Exhibit A]]. Related: [[deposition transcript]].",
    ),
    (
        "Contract p.1",
        "Subscription terms: auto-renew monthly at $19.99 with a $25.00 "
        "cancellation fee. Fee schedule: [[fee schedule 2026]]. "
        "See [[Complaint \u2014 Doe v. Voltmax]].",
    ),
    (
        "Exhibit A",
        "Bank statement: unauthorized charge of $30.00 on 2026-03-04. "
        "Cross-reference [[Complaint \u2014 Doe v. Voltmax]].",
    ),
)

DISCOVERY_JS = """
function esc(s){return s.replace(/[&<>"]/g,function(c){
return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function refreshCount(){var rows=document.querySelectorAll('.docrow'),n=0;
for(var i=0;i<rows.length;i++){if(rows[i].style.display!=='none')n++;}
var el=document.getElementById('count');
if(el)el.textContent=n+(n===1?' document in review set':' documents in review set');}
function filterDocs(){var q=(document.getElementById('filter').value||'').toLowerCase();
var rows=document.querySelectorAll('.docrow');
for(var i=0;i<rows.length;i++){
rows[i].style.display=rows[i].textContent.toLowerCase().indexOf(q)>=0?'':'none';}
refreshCount();}
var loadedAt=Date.now();
setInterval(function(){var a=document.getElementById('ago');
if(!a)return;var s=Math.floor((Date.now()-loadedAt)/1000);
a.textContent=s<5?'just now':(s<60?s+'s ago':Math.floor(s/60)+'m ago');},1000);
function jumpTo(id){var el=document.getElementById(id);
if(el){if(el.tagName==='DETAILS')el.open=true;
el.scrollIntoView({block:'center'});}}
function focusDoc(){var t=document.getElementById('doctext');
if(t){t.focus();window.scrollTo(0,0);}}
var currentDoc=null;
function openDoc(id){
var d=window.DOCS?window.DOCS[id]:null;
if(!d)return;
currentDoc=id;
document.getElementById('mtitle').textContent=d.name;
document.getElementById('mmeta').innerHTML='<code>'+esc(d.doc_id)+
'</code> <span class="ok">coded</span> <span class="dim">collected '+
esc(d.ingested_at)+'</span>';
document.getElementById('mchips').innerHTML=d.chips.map(function(c){
return '<span class="chip">'+esc(c)+'</span>';}).join(' ');
var backs=d.backlinks.map(function(b){
return '<a href="#'+esc(b)+'">'+esc(b)+'</a>';}).join(', ')||'(no backlinks yet)';
document.getElementById('mbody').innerHTML=d.html+
'<p class="dim">linked from: '+backs+'</p>'+
'<div class="btn-row"><button type="button" onclick="jumpFromModal()">'+
'open full entry</button></div>';
var m=document.getElementById('modal');
if(m)m.classList.add('open');
}
function openNode(n){
var m=document.getElementById('modal');
if(!m)return;
if(n.ghost){
currentDoc=null;
document.getElementById('mtitle').textContent='[['+n.label+']]';
document.getElementById('mmeta').innerHTML='<span class="dim">'+
'unresolved link</span>';
document.getElementById('mchips').innerHTML='';
document.getElementById('mbody').innerHTML='<p>no document named "'+
esc(n.label)+'" is in the review set yet \u2014 add it and the link '+
'resolves.</p>';
m.classList.add('open');
return;}
openDoc(n.id);}
function closeDoc(){var m=document.getElementById('modal');
if(m)m.classList.remove('open');}
function jumpFromModal(){closeDoc();if(currentDoc)jumpTo(currentDoc);}
function recall(ev){ev.preventDefault();
var box=document.getElementById('rr');
box.textContent='searching...';
fetch('/recall?q='+encodeURIComponent(document.getElementById('rq').value.trim()))
.then(function(r){return r.json();}).then(function(d){
var h='';
d.documents.forEach(function(x){
h+='<p><code>'+esc(x.doc_id)+'</code> '+esc(x.name)+
' <span class="ok">responsive</span><br><span class="dim">'+esc(x.snippet)+
'</span></p>';});
d.violations.forEach(function(x){
h+='<p><span class="chip">'+esc(x.source)+'</span> '+esc(x.id)+
' \u2014 '+esc(x.program)+'</p>';});
box.innerHTML=h||'<p class="dim">no responsive records</p>';
}).catch(function(){box.textContent='search failed';});}
function drawGraph(){
var host=document.getElementById('graph');
if(!host)return;
if(!window.GRAPH||!window.GRAPH.nodes.length){
host.innerHTML='<span class="dim">add documents to see the graph</span>';return;}
var W=host.clientWidth-14,H=320,NS='http://www.w3.org/2000/svg';
var nodes=window.GRAPH.nodes.map(function(n){
return {id:n.id,label:n.label,ghost:n.ghost,ca:n.ca,
x:24+Math.random()*(W-48),y:20+Math.random()*(H-40),vx:0,vy:0,d:0};});
var idx={};nodes.forEach(function(n,i){idx[n.id]=i;});
var links=[];
window.GRAPH.edges.forEach(function(e){
if(idx[e.s]!==undefined&&idx[e.t]!==undefined){
var s=idx[e.s],t=idx[e.t];
links.push({s:s,t:t});nodes[s].d++;nodes[t].d++;}});
nodes.forEach(function(n){n.r=n.ghost?5:Math.min(16,7+2*n.d);});
var svg=document.createElementNS(NS,'svg');
svg.setAttribute('width','100%');svg.setAttribute('height',H);
svg.setAttribute('viewBox','0 0 '+W+' '+H);
host.appendChild(svg);
var lines=links.map(function(){var l=document.createElementNS(NS,'line');
l.setAttribute('stroke','#b2b2b2');l.setAttribute('stroke-dasharray','3 3');
svg.appendChild(l);return l;});
var marks=nodes.map(function(n){var g=document.createElementNS(NS,'g');
var c=document.createElementNS(NS,'circle');
c.setAttribute('r',n.r);
c.setAttribute('fill',n.ghost?'#fff':(n.ca?'#006837':'#0071bb'));
c.setAttribute('stroke',n.ghost?'#b2b2b2':'#0f0e12');
var t=document.createElementNS(NS,'text');
t.setAttribute('font-size','11');t.setAttribute('fill','#0f0e12');
t.setAttribute('x',String(n.r+5));t.setAttribute('y','4');
t.textContent=n.label;
var tip=document.createElementNS(NS,'title');
tip.textContent=n.label;
g.appendChild(c);g.appendChild(t);g.appendChild(tip);
svg.appendChild(g);return g;});
var dragging=-1,dragMoved=false;
function place(){
nodes.forEach(function(n,i){marks[i].setAttribute('transform',
'translate('+n.x.toFixed(1)+','+n.y.toFixed(1)+')');});
lines.forEach(function(l,i){var a=nodes[links[i].s],b=nodes[links[i].t];
l.setAttribute('x1',a.x.toFixed(1));l.setAttribute('y1',a.y.toFixed(1));
l.setAttribute('x2',b.x.toFixed(1));l.setAttribute('y2',b.y.toFixed(1));});}
function neighbors(i){var set={};set[i]=1;
links.forEach(function(L){if(L.s===i)set[L.t]=1;if(L.t===i)set[L.s]=1;});
return set;}
function highlight(i){
var set=i<0?null:neighbors(i);
nodes.forEach(function(n,k){marks[k].style.opacity=!set||set[k]?'1':'0.12';});
lines.forEach(function(l,k){var L=links[k];
l.style.opacity=!set||set[L.s]||set[L.t]?'1':'0.1';});}
marks.forEach(function(g,i){
g.addEventListener('mouseenter',function(){if(dragging<0)highlight(i);});
g.addEventListener('mouseleave',function(){if(dragging<0)highlight(-1);});
g.addEventListener('mousedown',function(ev){
dragMoved=false;dragging=i;
nodes[i].vx=0;nodes[i].vy=0;ev.preventDefault();});
g.addEventListener('click',function(){if(!dragMoved)openNode(nodes[i]);});});
svg.addEventListener('mousemove',function(ev){
if(dragging<0)return;
dragMoved=true;
var r=svg.getBoundingClientRect();
nodes[dragging].x=(ev.clientX-r.left)/r.width*W;
nodes[dragging].y=(ev.clientY-r.top)/r.height*H;
place();});
svg.addEventListener('mouseup',function(){dragging=-1;});
var ticks=0;
function step(){
var i,j,a,b,dx,dy,d,f;
for(var k=0;k<3&&ticks<360;k++,ticks++){
for(i=0;i<nodes.length;i++){a=nodes[i];
if(i===dragging)continue;
for(j=i+1;j<nodes.length;j++){b=nodes[j];
if(j===dragging)continue;
dx=a.x-b.x;dy=a.y-b.y;d=Math.sqrt(dx*dx+dy*dy)||1;
f=1800/(d*d);a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f;}}
links.forEach(function(L){var a2=nodes[L.s],b2=nodes[L.t];
dx=b2.x-a2.x;dy=b2.y-a2.y;d=Math.sqrt(dx*dx+dy*dy)||1;
f=(d-110)*0.03;a2.vx+=dx/d*f;a2.vy+=dy/d*f;b2.vx-=dx/d*f;b2.vy-=dy/d*f;});
nodes.forEach(function(n){n.vx*=0.86;n.vy*=0.86;
n.x=Math.max(24,Math.min(W-24,n.x+n.vx));
n.y=Math.max(16,Math.min(H-16,n.y+n.vy));});}
place();
if(ticks<360)requestAnimationFrame(step);}
step();}
document.addEventListener('DOMContentLoaded',function(){
drawGraph();
document.addEventListener('click',function(ev){
var a=ev.target&&ev.target.closest?ev.target.closest('a[href^="#"]'):null;
var h=a?a.getAttribute('href'):null;
if(h&&h.length>1&&h.charAt(0)==='#'){ev.preventDefault();
closeDoc();jumpTo(h.slice(1));}});
var m=document.getElementById('modal');
if(m)m.addEventListener('click',function(ev){if(ev.target===m)closeDoc();});
var mc=document.getElementById('mclose');
if(mc)mc.addEventListener('click',closeDoc);
document.addEventListener('keydown',function(ev){
if(ev.key==='Escape')closeDoc();});
var f=document.getElementById('recallForm');
if(f)f.addEventListener('submit',recall);});
"""

PAGE_CSS = """
:root{--o:#f05a24;--b:#0071bb;--y:#fab413;--g:#006837;--k:#0f0e12;--w:#fff;
--tw:#f5f5f5;--g1:#e5e5e5;--g3:#b2b2b2;--g9:#4d4d4d}
*{box-sizing:border-box}
body{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;font-weight:300;
margin:0;background:var(--w);color:var(--k);line-height:1.5}
a{color:var(--k);text-decoration:underline;text-underline-offset:2px}
code{font-family:ui-monospace,Menlo,Consolas,monospace;background:var(--g1);
padding:.1em .3em;border:1px solid var(--g3);font-size:.85em}
pre{font-family:ui-monospace,Menlo,Consolas,monospace;background:var(--w);
color:var(--k);border:1px solid var(--g3);padding:.75rem;white-space:pre-wrap;
word-break:break-word;font-size:.85em}
.container{max-width:1180px;margin:0 auto;padding:2rem 1.5rem}
.header{display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;
border-bottom:1px solid var(--k);padding-bottom:.75rem;margin-bottom:1.5rem;
flex-wrap:wrap;animation:fadein .3s ease-out both}
.header h1{font-size:2.4rem;font-weight:300;letter-spacing:-.02em;margin:0}
.badge{display:inline-block;border:1px solid var(--k);background:var(--y);
padding:.2rem .6rem;font-size:.75rem;margin-top:.35rem;
text-transform:lowercase}
nav a{font-size:.85rem;font-weight:300;text-decoration:none;
text-transform:lowercase}
nav a+a{margin-left:1.25rem}
nav a:hover{text-decoration:underline}
.card{border:1px solid var(--g3);padding:1.25rem;margin-bottom:1.25rem;
background:var(--w);animation:rise .3s ease-out both}
.card:nth-of-type(2){animation-delay:.04s}
.card:nth-of-type(3){animation-delay:.08s}
.card:nth-of-type(4){animation-delay:.12s}
.card:nth-of-type(n+5){animation-delay:.16s}
.card h3{margin:0 0 .75rem;font-size:.9rem;font-weight:300;
border-bottom:1px solid var(--g1);padding-bottom:.4rem;
text-transform:lowercase}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:.75rem}
.card.stats{padding:.75rem}
.stat{border:1px solid var(--k);padding:.9rem;
transition:transform .12s ease-out,box-shadow .12s ease-out}
.stat:hover{transform:translate(-3px,-3px);box-shadow:3px 3px 0 var(--k)}
.stat:nth-of-type(4n+1){background:var(--o);color:var(--w)}
.stat:nth-of-type(4n+2){background:var(--b);color:var(--w)}
.stat:nth-of-type(4n+3){background:var(--y);color:var(--k)}
.stat:nth-of-type(4n+4){background:var(--g);color:var(--w)}
.stat .n{font-size:2.4rem;font-weight:400;line-height:1}
.stat .l{font-size:.7rem;margin-top:.35rem;text-transform:lowercase}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th,td{text-align:left;padding:.5rem .6rem;border:1px solid var(--g3)}
th{background:var(--k);color:var(--tw);font-weight:300;font-size:.8rem;
text-transform:lowercase}
tr:hover td{background:var(--tw)}
.chip{display:inline-block;border:1px solid var(--g3);background:var(--w);
padding:.05rem .45rem;font-size:.7rem;text-transform:lowercase}
.warning{background:var(--y);border:1px solid var(--k);padding:.75rem;
margin:.6rem 0}
.ok{display:inline-block;background:var(--g);color:var(--w);
border:1px solid var(--k);padding:.05rem .5rem;font-size:.75rem;
text-transform:lowercase}
.dim{color:var(--g9);font-size:.8rem}
.suit{border-bottom:1px solid var(--g1);padding:.9rem 0}
.suit:last-child{border-bottom:none}
.btn-row{display:flex;gap:.5rem;align-items:center;margin:.5rem 0}
details{margin:.4rem 0;border-top:1px solid var(--g1);padding-top:.4rem}
details>summary{cursor:pointer;font-weight:400;font-size:.9rem}
form .row{margin:.5rem 0}
form label{display:block;font-size:.8rem;font-weight:300;margin-bottom:.25rem;
text-transform:lowercase}
form input[type=text],form textarea{
width:100%;background:var(--w);border:1px solid var(--g3);color:var(--k);
padding:.5rem;border-radius:0;font-size:.9rem;font-weight:300;
font-family:ui-monospace,Menlo,Consolas,monospace}
form textarea{min-height:140px}
form select{width:100%;background:var(--w);border:1px solid var(--g3);
color:var(--k);padding:.5rem;border-radius:0;font-size:.9rem;
font-family:inherit}
.btn-row input{flex:1;min-width:0}
#graph{border:1px solid var(--g1);padding:.5rem;overflow:hidden}
#graph svg{display:block}
#rr p{margin:.4rem 0}
.barrow{display:flex;align-items:center;gap:.6rem;margin:.35rem 0;
font-size:.8rem}
.barlab{width:9rem;text-transform:lowercase}
.battrack{flex:1;background:var(--g1);height:14px}
.batfill{height:14px;display:block}
.barval{width:2rem;text-align:right}
.modal{position:fixed;inset:0;background:rgba(15,14,18,.55);display:flex;
align-items:center;justify-content:center;z-index:20;opacity:0;
transition:opacity .15s;pointer-events:none}
.modal.open{opacity:1;pointer-events:auto}
.modalbox{background:var(--w);border:1px solid var(--k);
width:min(720px,92vw);max-height:84vh;overflow:auto;padding:1.25rem}
.modalhead{display:flex;justify-content:space-between;align-items:baseline;
gap:1rem;border-bottom:1px solid var(--g1);padding-bottom:.5rem;
margin-bottom:.75rem}
.modalhead h3{margin:0;font-weight:300;font-size:1.15rem}
.mclose{background:none;border:none;font-size:1.5rem;cursor:pointer;
padding:0 .3rem;line-height:1}
.btn{display:inline-block;background:var(--k);color:var(--tw);
padding:.55rem 1.2rem;font-size:.85rem;font-weight:300;
text-transform:lowercase;text-decoration:none}
.btn:hover{opacity:.7}
form input:focus,form textarea:focus{outline:none;border-color:var(--b)}
button{background:var(--k);color:var(--tw);border:none;border-radius:0;
padding:.55rem 1.2rem;cursor:pointer;font-size:.85rem;font-weight:300;
font-family:inherit;text-transform:lowercase}
button:hover{opacity:.7}
.hud{background:var(--k);border:1px solid var(--k);padding:1rem;min-height:200px;
font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.8rem;
line-height:1.7;color:var(--tw);overflow:hidden}
.hud div{animation:slidein .25s ease-out both}
.hud .seq{color:#767676}
.hud .spk{color:var(--y);font-weight:400}
.hud .txt{color:var(--tw)}
.hud .obj{color:var(--o);margin-left:1rem}
.hud .prm{color:#4cc38a;margin-left:1rem}
.live-dot{display:inline-block;width:.55em;height:.55em;background:var(--o);
border-radius:50%;margin-left:.4rem;vertical-align:middle}
footer{text-align:center;font-size:.7rem;margin-top:2rem;padding-top:1rem;
border-top:1px solid var(--g3);text-transform:lowercase}
@keyframes fadein{from{opacity:0}to{opacity:1}}
@keyframes rise{from{opacity:0;transform:translateY(10px)}
to{opacity:1;transform:translateY(0)}}
@keyframes slidein{from{opacity:0;transform:translateX(-12px)}
to{opacity:1;transform:translateX(0)}}
@media (prefers-reduced-motion:reduce){
*{animation:none!important;transition:none!important}}
"""


HUD_JS = r"""
function connectHud() {
  var es = new EventSource("/hud/stream");
  var box = document.getElementById("hud");
  es.addEventListener("frame", function (e) {
    var f = JSON.parse(e.data);
    var div = document.createElement("div");
    div.innerHTML = '<span class="seq">#' + f.seq + '</span> ' +
      '<span class="spk">' + htmlEscape(f.speaker) + ':</span> ' +
      '<span class="txt">' + htmlEscape(f.transcript) + '</span>';
    if (f.objections && f.objections.length) {
      f.objections.forEach(function (o) {
        var od = document.createElement("div");
        od.className = "obj";
        od.textContent = "  OBJECTION " + o.label + " (" + o.citation + ") conf=" + o.confidence.toFixed(2);
        div.appendChild(od);
      });
    }
    if (f.prompt) {
      var pd = document.createElement("div");
      pd.className = "prm";
      pd.textContent = "  HUD PROMPT> " + f.prompt;
      div.appendChild(pd);
    }
    box.appendChild(div);
    if (box.children.length > 20) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
  });
  es.onerror = function () {
    es.close();
    setTimeout(connectHud, 800);
  };
}
function htmlEscape(s) {
  var m = {"&": "&", "<": "<", ">": ">", "\"": "\"", "'": "&#039;"};
  return s.replace(/[&<>"']/g, function (c) { return m[c]; });
}
document.addEventListener("DOMContentLoaded", connectHud);
"""


def _bar(label: str, value: int, maximum: int, color: str) -> str:
    pct = int(round(100 * value / maximum)) if maximum else 0
    e = html.escape
    return (
        f"<div class=\"barrow\"><span class=\"barlab\">{e(label)}</span>"
        f"<span class=\"battrack\"><span class=\"batfill\" "
        f"style=\"width:{pct}%;background:{color}\"></span></span>"
        f"<span class=\"barval\">{value}</span></div>"
    )


def render_dashboard(result: PipelineResult) -> str:
    e = html.escape
    parts = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\"><title>LexGlasses Dashboard</title>",
        f"<style>{PAGE_CSS}</style>",
        f"<script>{HUD_JS}</script>",
        "</head><body>",
        "<div class=\"container\">",
        "<header class=\"header\">",
        "<div><h1>LexGlasses</h1><div class=\"badge\">Project JusticeStack \u2014 simulation, not legal advice</div></div>",
        NAV,
        "</header>",
        "<section class=\"card stats\">",
        f"<div class=\"stat\"><div class=\"n\">{result.total_violations}</div><div class=\"l\">records collected</div></div>",
        f"<div class=\"stat\"><div class=\"n\">{len(result.matches)}</div><div class=\"l\">auto matches (\u2265 {MIN_AUTO_CONFIDENCE:.2f})</div></div>",
        f"<div class=\"stat\"><div class=\"n\">{len(result.review)}</div><div class=\"l\">human review</div></div>",
        f"<div class=\"stat\"><div class=\"n\">{len(result.drafts)}</div><div class=\"l\">draft documents</div></div>",
        "</section>",
    ]
    overview = (
        ("records collected", result.total_violations, "#0071bb"),
        ("matched claims", len(result.matches), "#006837"),
        ("held for review", len(result.review), "#fab413"),
        ("draft documents", len(result.drafts), "#f05a24"),
    )
    biggest = max(value for _, value, _ in overview) or 1
    parts.append("<section class=\"card\"><h3>Claims overview</h3>")
    for label, value, color in overview:
        parts.append(_bar(label, value, biggest, color))
    parts.append("</section>")

    if result.matches:
        parts.append("<section class=\"card\"><h3>Matched claims</h3><table>")
        parts.append("<tr><th>Violation ID</th><th>Program</th><th>Source</th><th>Claim</th><th>Confidence</th></tr>")
        for m in result.matches:
            v = m.violation
            parts.append(
                f"<tr><td><code>{e(v.id)}</code></td><td>{e(v.program)}</td>"
                f"<td>{e(v.source)}</td><td>{e(m.claim_type)}</td>"
                f"<td>{m.confidence:.2f}</td></tr>"
            )
        parts.append("</table></section>")

    if result.review:
        parts.append("<section class=\"card\"><h3>Held for Human Review</h3>")
        for m in result.review:
            v = m.violation
            parts.append(
                f"<div class=\"warning\"><strong>{e(v.id)}</strong> \u2014 {e(v.program)} "
                f"(confidence {m.confidence:.2f} < {MIN_AUTO_CONFIDENCE:.2f})"
            )
            for ev in m.evidence:
                parts.append(f"<div style=\"margin-left:1rem\">{e(ev)}</div>")
            parts.append("  \u2192 no document auto-generated; verify manually before acting</div>")
        parts.append("</section>")

    if result.case is not None:
        c = result.case
        parts.append(f"<section class=\"card\"><h3>Case {e(c.case_number)} \u2014 {e(c.cause)}</h3>")
        parts.append(f"<p>Current stage: <strong>{e(c.stage)}</strong></p>")
        parts.append("<ul>")
        for day, entry in c.history:
            parts.append(f"<li><code>{e(day)}</code> \u2014 {e(entry)}</li>")
        parts.append("</ul></section>")

    if result.briefing is not None:
        b = result.briefing
        parts.append(f"<section class=\"card\"><h3>Stage Briefing: {e(b.stage)} \u2014 {e(b.title)}</h3>")
        parts.append("<ul>")
        for item in b.checklist:
            parts.append(f"<li>[ ] {e(item)}</li>")
        parts.append(f"</ul><p class=\"warning\">{e(b.caution)}</p></section>")

    if result.tags is not None:
        parts.append("<section class=\"card\"><h3>Issues &amp; entities</h3><pre>")
        for line in result.tags.summary().splitlines():
            parts.append(e(line))
        parts.append("</pre></section>")

    if result.drafts:
        parts.append("<section class=\"card\"><h3>Draft Documents</h3>")
        for vid, d in result.drafts:
            parts.append(
                f"<details><summary>[<code>{e(vid)}</code>] {e(d.doc_type)} \u2192 {e(d.document_id)}</summary>"
                f"<pre>{e(d.text)}</pre></details>"
            )
        parts.append("</section>")

    parts.append("<section class=\"card\"><h3>Glasses HUD \u2014 live transcript"
                 "<span class=\"live-dot\"></span></h3>")
    parts.append("<div id=\"hud\" class=\"hud\"></div></section>")

    parts.append("<footer>DISCLAIMER: simulation output only. Not legal advice; not for filing.</footer>")
    parts.append("</div></body></html>")
    return "\n".join(parts)


def render_live_page(
    source: str, query: str | None, limit: int, violations: list[Violation]
) -> str:
    e = html.escape
    mdash = "\u2014"
    options = []
    for name in ("all", "cfpb", "recap", "ftc"):
        selected = " selected" if name == source else ""
        options.append(f"<option value=\"{name}\"{selected}>{name}</option>")
    parts = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\"><title>Collections \u2014 LexGlasses</title>",
        f"<style>{PAGE_CSS}</style>",
        "</head><body>",
        "<div class=\"container\">",
        "<header class=\"header\">",
        "<div><h1>Collections</h1>"
        "<div class=\"badge\">public esi \u2192 cfpb \u00b7 recap \u00b7 ftc</div></div>",
        NAV,
        "</header>",
        "<section class=\"card\">",
        "<h3>Collect from public sources</h3>",
        "<form method=\"GET\" action=\"/live\">",
        "<div class=\"row\"><label>source</label>"
        f"<select name=\"source\">{''.join(options)}</select></div>",
        "<div class=\"row\"><label>search terms</label>"
        f"<input type=\"text\" name=\"query\" value=\"{e(query or '')}\"></div>",
        "<div class=\"row\"><label>results</label>"
        f"<input type=\"text\" name=\"limit\" value=\"{limit}\"></div>",
        "<button type=\"submit\">collect</button>",
        "</form>",
        "</section>",
        "<section class=\"card\">",
        "<h3>Load case files (SD card / folder / zip)</h3>",
        "<form method=\"POST\" action=\"/import\">",
        "<div class=\"row\"><label>path on this machine</label>",
        "<input type=\"text\" name=\"path\" required "
        "placeholder=\"E:\\Smith v FitTrack\\productions\"></div>",
        "<button type=\"submit\">import case files</button>",
        "</form>",
        "<p class=\"dim\">plug in the card (or point at any folder / .zip) and "
        "your already-collected material lands in Discovery \u2014 every "
        ".txt .md .json .jsonl .csv .pdf is read, coded, and wikilinked. "
        "hidden and system folders are skipped.</p>",
        "</section>",
        f"<section class=\"card\"><p>source: <strong>{e(source)}</strong> {mdash} "
        f"terms: {e(query) if query else '(any)'} {mdash} limit: {limit}</p>",
        f"<p>collected <strong>{len(violations)}</strong> record(s).</p></section>",
    ]
    if violations:
        parts.append("<section class=\"card\"><h3>Violations</h3>")
        for v in violations:
            rules = ", ".join(r["type"] for r in v.rules) or "none"
            parts.append(
                f"<details><summary>[<code>{e(v.source)}</code>] {e(v.id)} {mdash} {e(v.program)} "
                f"(<span class=\"chip\">{e(v.status)}</span>) rules: {e(rules)}</summary>"
                f"<pre>{e(v.description)}</pre></details>"
            )
        parts.append("</section>")
    else:
        parts.append(
            "<section class=\"card\"><p>No records collected for these parameters.</p></section>"
        )

    parts.append("<footer>DISCLAIMER: live data from public sources. Not legal advice.</footer>")
    parts.append("</div></body></html>")
    return "\n".join(parts)


def render_doc_text(text: str, by_key: dict[str, DocumentRecord]) -> str:
    out: list[str] = []
    last = 0
    for match in LINK_RE.finditer(text):
        out.append(html.escape(text[last : match.start()]))
        target = match.group(1).strip()
        rec = by_key.get(target.lower())
        if rec is not None:
            out.append(f"<a href=\"#{rec.doc_id}\">{html.escape(target)}</a>")
        else:
            out.append(f"<span class=\"dim\">[[{html.escape(target)}]]</span>")
        last = match.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def render_documents_page(
    records: list[DocumentRecord],
    error: str | None = None,
    graph_data: dict | None = None,
    notice: str | None = None,
) -> str:
    e = html.escape
    graph_data = graph_data or {"nodes": [], "edges": [], "backlinks": {}}
    backlinks = graph_data["backlinks"]
    graph_json = json.dumps(graph_data, separators=(",", ":")).replace("<", "\\u003c")
    by_key: dict[str, DocumentRecord] = {}
    for rec in records:
        by_key[rec.name.strip().lower()] = rec
        by_key[rec.doc_id.lower()] = rec
    docs_payload: dict[str, dict] = {}
    for rec in records:
        tags = rec.tags.to_dict()
        body_html = (
            "<pre>"
            + e(rec.tags.summary())
            + "</pre><pre>"
            + render_doc_text(rec.text, by_key)
            + "</pre>"
        )
        docs_payload[rec.doc_id] = {
            "doc_id": rec.doc_id,
            "name": rec.name,
            "ingested_at": rec.ingested_at,
            "chips": tags["keywords"][:3] + tags["parties"][:2],
            "html": body_html,
            "backlinks": backlinks.get(rec.doc_id, []),
        }
    docs_json = json.dumps(docs_payload, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    count_word = "document" if len(records) == 1 else "documents"
    parts = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\"><title>Discovery \u2014 LexGlasses</title>",
        f"<style>{PAGE_CSS}</style>",
        f"<script>window.GRAPH={graph_json};</script>",
        f"<script>window.DOCS={docs_json};</script>",
        f"<script>{DISCOVERY_JS}</script>",
        "</head><body>",
        "<div class=\"container\">",
        "<header class=\"header\">",
        "<div><h1>Discovery</h1>"
        "<div class=\"badge\">review set \u2192 issue codes \u2192 recall</div></div>",
        NAV,
        "</header>",
    ]
    if notice:
        parts.append(f"<div class=\"warning\">{e(notice)}</div>")
    if error == "empty":
        parts.append(
            "<div class=\"warning\">no document text provided \u2014 "
            "nothing was added to the review set.</div>"
        )
    parts += [
        "<section class=\"card\">",
        "<h3>Add document to review set</h3>",
        "<form method=\"POST\" action=\"/documents\">",
        "<div class=\"row\"><label>description</label>"
        "<input type=\"text\" name=\"name\" "
        "placeholder=\"e.g. subscription contract p.1\"></div>",
        "<div class=\"row\"><label>document text (esi)</label>"
        "<textarea id=\"doctext\" name=\"text\" "
        "placeholder=\"paste the text of a complaint, contract, or exhibit\"></textarea>",
        "</div>",
        "<button type=\"submit\">add document</button>",
        "</form>",
        "</section>",
        "<section class=\"card\">",
        "<h3>Recall</h3>",
        "<p class=\"dim\">keyword search across the review set and collected "
        "records \u2014 surface responsive documents.</p>",
        "<form id=\"recallForm\" class=\"btn-row\">",
        "<input type=\"text\" id=\"rq\" placeholder=\"e.g. late fee, auto-renew\">",
        "<button type=\"submit\">search</button>",
        "</form>",
        "<div id=\"rr\"></div>",
        "</section>",
    ]
    if records:
        parts.append("<section class=\"card\">")
        parts.append(
            f"<p><span id=\"count\">{len(records)} {count_word} in review set</span>"
            " \u00b7 refreshed <span id=\"ago\">just now</span></p>"
        )
        parts.append(
            "<p><input type=\"text\" id=\"filter\" oninput=\"filterDocs()\" "
            "placeholder=\"filter by id, description, or issue\" "
            "style=\"width:100%\"></p>"
        )
        for rec in records:
            doc = docs_payload[rec.doc_id]
            chips = " ".join(
                f"<span class=\"chip\">{e(c)}</span>" for c in doc["chips"]
            )
            back = doc["backlinks"]
            linked = f" \u00b7 {len(back)} linked" if back else ""
            parts.append(
                f"<details class=\"docrow\" id=\"{e(rec.doc_id)}\">"
                f"<summary><code>{e(rec.doc_id)}</code> {e(rec.name)} "
                f"{chips} "
                "<span class=\"ok\" title=\"issue codes extracted and stored\">coded</span>"
                f"<span class=\"dim\">collected {e(rec.ingested_at)}{linked}"
                "</span></summary>"
            )
            parts.append(doc["html"])
            if back:
                links = ", ".join(
                    f"<a href=\"#{e(bid)}\">{e(bid)}</a>" for bid in back
                )
                parts.append(f"<p class=\"dim\">linked from: {links}</p>")
            parts.append("</details>")
        parts.append("</section>")
        counts: dict[str, int] = {}
        for rec in records:
            for kw in rec.tags.keywords:
                counts[kw] = counts.get(kw, 0) + 1
        if counts:
            parts.append("<section class=\"card\"><h3>Issues in the review set</h3>")
            top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            for kw, n in top:
                parts.append(_bar(kw, n, top[0][1], "#f05a24"))
            parts.append("</section>")
    else:
        parts.append(
            "<section class=\"card\">"
            "<p>No documents yet \u2014 the review set is empty. link documents "
            "with <code>[[double brackets]]</code> to build the graph.</p>"
            "<div class=\"btn-row\">"
            "<button type=\"button\" onclick=\"focusDoc()\">"
            "add first document</button>"
            "<form method=\"POST\" action=\"/documents/sample\">"
            "<button type=\"submit\">load example review set</button>"
            "</form></div>"
            "</section>"
        )
    parts.append("<section class=\"card\">")
    parts.append("<h3>Graph \u2014 review set links</h3>")
    parts.append(
        "<p class=\"dim\">[[wikilinks]] between documents; dashed = unresolved; "
        "green = class action. hover to spotlight a neighborhood, "
        "drag to arrange, click to open.</p>"
    )
    parts.append("<div id=\"graph\"></div>")
    if len(records) < 3:
        parts.append(
            "<form method=\"POST\" action=\"/documents/sample\" class=\"btn-row\">"
            "<button type=\"submit\">load example review set</button>"
            "</form>"
        )
    parts.append("</section>")
    parts.append(
        "<div id=\"modal\" class=\"modal\">"
        "<div class=\"modalbox\">"
        "<div class=\"modalhead\"><h3 id=\"mtitle\"></h3>"
        "<button type=\"button\" class=\"mclose\" id=\"mclose\" "
        "aria-label=\"close\">&times;</button></div>"
        "<p id=\"mmeta\"></p><p id=\"mchips\"></p><div id=\"mbody\"></div>"
        "</div></div>"
    )
    parts.append(
        "<footer>DISCLAIMER: the review set is held in memory for this session "
        "only. Not legal advice.</footer>"
    )
    parts.append("</div></body></html>")
    return "\n".join(parts)


def render_suits_page(
    query: str | None,
    limit: int,
    violations: list[Violation],
    joins: list[dict],
    notice: str | None = None,
) -> str:
    e = html.escape
    effective = query or DEFAULT_SUIT_QUERY
    joined_ids = {j["violation_id"] for j in joins}
    parts = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\"><title>Class actions</title>",
        f"<style>{PAGE_CSS}</style>",
        "</head><body>",
        "<div class=\"container\">",
        "<header class=\"header\">",
        "<div><h1>Class action finder</h1>"
        "<div class=\"badge\">search RECAP \u2192 match your record \u2192 draft joinder</div></div>",
        NAV,
        "</header>",
    ]
    if notice:
        parts.append(f"<div class=\"warning\">{e(notice)}</div>")
    parts += [
        "<section class=\"card\">",
        "<form method=\"GET\" action=\"/suits\">",
        "<div class=\"row\"><label>search terms</label>"
        f"<input type=\"text\" name=\"query\" value=\"{e(effective)}\"></div>",
        "<div class=\"row\"><label>results</label>"
        f"<input type=\"text\" name=\"limit\" value=\"{limit}\"></div>",
        "<button type=\"submit\">search dockets</button>",
        "<button type=\"submit\" formaction=\"/suits/auto-join\" "
        "formmethod=\"POST\">auto-enroll matches</button>",
        "</form>",
        f"<p class=\"dim\">auto-enroll joins every discovered suit that matches "
        f"your record at confidence \u2265 {MIN_AUTO_CONFIDENCE:.2f}; the rest "
        "stay in review.</p>",
        "</section>",
        f"<section class=\"card\"><h3>Discovered suits ({len(violations)})</h3>",
    ]
    if not violations:
        parts.append("<p>No suits found for this query.</p>")
    for v in violations:
        match = evaluate(v, SAMPLE_RECORD)
        rules = ", ".join(r["type"] for r in v.rules) or "none"
        parts.append("<div class=\"suit\">")
        parts.append(
            f"<p><strong>{e(v.program)}</strong> "
            f"<span class=\"chip\">{e(v.source)}</span> "
            f"<span class=\"chip\">{e(v.status)}</span> rules: {e(rules)}</p>"
        )
        if match is not None:
            parts.append(
                f"<p><span class=\"ok\">matches your record \u2014 {match.confidence:.2f}</span></p>"
            )
            for ev in match.evidence:
                parts.append(f"<p style=\"margin-left:1rem\">{e(ev)}</p>")
        else:
            parts.append(
                "<p class=\"dim\">not auto-matched to your record "
                "(verify membership yourself)</p>"
            )
        for url in URL_RE.findall(v.description)[:3]:
            parts.append(
                f"<p><a href=\"{e(url.rstrip('.'))}\" rel=\"noopener\">"
                f"reference: {e(url.rstrip('.'))}</a></p>"
            )
        if v.id in joined_ids:
            parts.append(
                "<p><span class=\"ok\">joined \u2014 draft joinder ready (see below)</span></p>"
            )
        else:
            hidden = e(json.dumps(violation_to_json(v)), quote=True)
            parts.append(
                "<form method=\"POST\" action=\"/suits/join\" class=\"btn-row\">"
                f"<input type=\"hidden\" name=\"violation\" value=\"{hidden}\">"
                "<button type=\"submit\">join \u2014 draft joinder</button>"
                "</form>"
            )
        parts.append("</div>")
    parts.append("</section>")
    if joins:
        parts.append("<section class=\"card\"><h3>Joinders (drafts)</h3>")
        for j in joins:
            auto_chip = "<span class=\"chip\">auto</span>" if j.get("auto") else ""
            parts.append(
                f"<details><summary><code>{e(j['violation_id'])}</code> {e(j['program'])} "
                f"\u2014 <span class=\"ok\">{e(j['status'])}</span> {auto_chip} "
                f"(file by {e(j.get('file_by', 'n/a'))}) ({e(j['joined_at'])})"
                f"</summary><pre>{e(j['draft'])}</pre></details>"
            )
        parts.append("</section>")
    parts.append(
        "<footer>DISCLAIMER: drafts only; verify class membership and "
        "deadlines with counsel.</footer>"
    )
    parts.append("</div></body></html>")
    return "\n".join(parts)


EXPORT_ITEMS = (
    ("/api/simulate", "case-file.json", "/exports/case-file", "case file",
     "claims, case timeline, stage briefings, drafts, hearing frames"),
    ("/documents.json", "review-set.json", "/documents", "review set",
     "coded documents with issues, wikilinks, and Bates ids"),
    ("/graph.json", "graph.json", "/documents#graph", "link graph",
     "documents, wikilinks, backlinks, unresolved targets"),
    ("/joins.json", "joinders.json", "/suits", "joinders",
     "draft joinders with confidence and filing deadlines"),
    ("/live.json?source=all&limit=10", "collected.json", "/live", "collected records",
     "public esi from cfpb, recap, and ftc (last collection)"),
    ("/recall?q=", "recall.json", "/documents#recallForm", "recall",
     "keyword search across the review set and collected records"),
)


def render_exports_page(result: PipelineResult) -> str:
    e = html.escape
    parts = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\"><title>Exports \u2014 LexGlasses</title>",
        f"<style>{PAGE_CSS}</style>",
        "</head><body>",
        "<div class=\"container\">",
        "<header class=\"header\">",
        "<div><h1>Exports</h1>"
        "<div class=\"badge\">productions for your records \u2192 json</div></div>",
        NAV,
        "</header>",
        "<section class=\"card\"><h3>Available productions</h3>",
    ]
    for href, filename, open_href, title, desc in EXPORT_ITEMS:
        parts.append(
            "<div class=\"suit\">"
            f"<p><strong>{e(title)}</strong></p>"
            f"<p class=\"dim\">{e(desc)}</p>"
            "<p class=\"btn-row\">"
            f"<a class=\"btn\" href=\"{e(href)}\" download=\"{e(filename)}\">"
            "download</a>"
            f"<a class=\"btn\" href=\"{e(open_href)}\">open</a>"
            "</p></div>"
        )
    parts.append("</section>")
    payload = e(json.dumps(simulate_result_json(result), indent=2))
    parts.append(
        "<section class=\"card\"><h3>Preview \u2014 case file</h3>"
        "<details><summary>show formatted json</summary>"
        f"<pre>{payload}</pre></details></section>"
    )
    parts.append(
        "<footer>DISCLAIMER: exports are working records for your own files. "
        "Not legal advice.</footer>"
    )
    parts.append("</div></body></html>")
    return "\n".join(parts)


def render_case_file_page(result: PipelineResult) -> str:
    e = html.escape
    data = simulate_result_json(result)
    parts = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\"><title>Case file \u2014 LexGlasses</title>",
        f"<style>{PAGE_CSS}</style>",
        "</head><body>",
        "<div class=\"container\">",
        "<header class=\"header\">",
        "<div><h1>Case file</h1>"
        "<div class=\"badge\">claims \u00b7 timeline \u00b7 drafts \u00b7 hearing prep</div></div>",
        NAV,
        "</header>",
    ]

    def match_card(m: dict, dim_note: str | None = None) -> None:
        conf = f"{m['confidence'] * 100:.0f}%"
        evidence = "".join(f"<li>{e(x)}</li>" for x in m["evidence"])
        parts.append(
            f"<div class=\"suit\"><p><strong>{e(m['program'])}</strong></p>"
            f"<p><span class=\"chip\">{e(m['claim_type'])}</span>"
            f"<span class=\"chip\">{e(m['source'])}</span>"
            f"<span class=\"chip\">confidence {conf}</span></p>"
        )
        if dim_note:
            parts.append(f"<p class=\"dim\">{e(dim_note)}</p>")
        parts.append(f"<ul>{evidence}</ul></div>")

    parts.append("<section class=\"card\"><h3>Matched claims</h3>")
    if data["matches"]:
        for m in data["matches"]:
            match_card(m)
    else:
        parts.append("<p class=\"dim\">no claims auto-matched yet.</p>")
    parts.append("</section>")

    if data["review"]:
        parts.append("<section class=\"card\"><h3>Below threshold \u2014 in review</h3>")
        for m in data["review"]:
            match_card(m, f"under {data['min_auto_confidence']:.2f} \u2014 verify before filing")
        parts.append("</section>")

    if data["case"]:
        case = data["case"]
        parts.append(
            "<section class=\"card\"><h3>Case timeline</h3>"
            f"<p><span class=\"chip\">{e(case['case_number'])}</span>"
            f"<span class=\"chip\">{e(case['stage'])}</span></p>"
            f"<p><strong>{e(case['cause'])}</strong></p>"
            f"<p>{e(case['party'])}</p>"
        )
        for entry in case["history"]:
            parts.append(f"<p class=\"dim\">{e(entry['day'])} \u2014 {e(entry['entry'])}</p>")
        parts.append("</section>")

    if data["briefing"]:
        brief = data["briefing"]
        checklist = "".join(f"<li>{e(c)}</li>" for c in brief["checklist"])
        parts.append(
            "<section class=\"card\">"
            f"<h3>Stage briefing \u2014 {e(brief['title'])}</h3>"
            f"<ol>{checklist}</ol>"
            f"<p class=\"warning\">{e(brief['caution'])}</p></section>"
        )

    if data["tags"]:
        parts.append(
            "<section class=\"card\"><h3>Issue codes</h3><pre>"
            + e("\n".join(data["tags"]))
            + "</pre></section>"
        )

    if data["drafts"]:
        parts.append("<section class=\"card\"><h3>Drafts</h3>")
        for d in data["drafts"]:
            parts.append(
                f"<details><summary>{e(d['doc_type'])} \u2014 "
                f"<code>{e(d['document_id'])}</code></summary>"
                f"<pre>{e(d['text'])}</pre></details>"
            )
        parts.append("</section>")

    if data["frames"]:
        parts.append("<section class=\"card\"><h3>Hearing prep \u2014 frames</h3>")
        for f in data["frames"]:
            chips = "".join(
                f"<span class=\"chip\">{e(o['label'])} {e(o['citation'])}</span>"
                for o in f["objections"]
            )
            parts.append(
                f"<div class=\"suit\"><p><strong>frame {f['seq']} \u2014 "
                f"{e(f['speaker'])}</strong></p>"
                f"<p>{e(f['transcript'])}</p>"
                f"<p class=\"warning\">{e(f['prompt'])}</p>"
                f"<p>{chips}</p></div>"
            )
        parts.append("</section>")

    parts.append(
        "<footer>DISCLAIMER: working case file \u2014 verify every deadline and "
        "citation. Not legal advice.</footer>"
    )
    parts.append("</div></body></html>")
    return "\n".join(parts)


def _clamp_limit(text: str, default: int = 10) -> int:
    try:
        val = int(text)
        return max(1, min(50, val))
    except (ValueError, TypeError):
        return default


def _live_params(params: dict[str, list[str]]) -> tuple[str, str | None, int]:
    source = params.get("source", ["all"])[0]
    if source not in ("cfpb", "recap", "ftc", "all"):
        source = "all"
    query = params.get("query", [None])[0]
    limit = _clamp_limit(params.get("limit", ["10"])[0])
    return source, query, limit


class WebApp:
    def __init__(self, live_ttl_seconds: float = 30.0) -> None:
        self.live_ttl_seconds = live_ttl_seconds
        self._lock = threading.Lock()
        self._simulate: PipelineResult | None = None
        self._runs = 0
        self._live: dict[tuple[str, str, int], tuple[float, list[Violation]]] = {}
        self._documents: list[DocumentRecord] = []
        self._joins: list[dict] = []
        self.copilot = CopilotHub()
        self.vocabulary = VocabularyStore()
        self.research = ResearchStore(self.vocabulary.directory)
        self.practice = DebateHub(self.vocabulary, self.research)

    def simulate(self) -> PipelineResult:
        with self._lock:
            if self._simulate is None:
                self._simulate = run()
                self._runs += 1
            return self._simulate

    def live(self, source: str, query: str | None, limit: int) -> list[Violation]:
        key = (source, query or "", limit)
        with self._lock:
            hit = self._live.get(key)
            if hit is not None and time.monotonic() - hit[0] < self.live_ttl_seconds:
                return hit[1]
        violations = collect(build_live_sources(source, query, limit), rate_limit_seconds=1.0)
        with self._lock:
            self._live[key] = (time.monotonic(), violations)
        return violations

    def add_document(self, name: str, text: str) -> DocumentRecord:
        with self._lock:
            rec = DocumentRecord(
                doc_id=f"PROSE-{len(self._documents) + 1:06d}",
                name=name.strip() or "untitled",
                ingested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                text=text,
                tags=tag_text(text),
                links=tuple(dict.fromkeys(LINK_RE.findall(text))),
            )
            self._documents.append(rec)
            return rec

    def import_path(self, raw: str) -> dict:
        items = ingest.load(raw)
        existing = {r.name.strip().lower() for r in self.documents()}
        added = 0
        skipped = 0
        for name, text in items:
            if name.lower() in existing:
                skipped += 1
                continue
            self.add_document(name, text)
            existing.add(name.lower())
            added += 1
        return {"added": added, "skipped": skipped, "found": len(items)}

    def documents(self) -> list[DocumentRecord]:
        with self._lock:
            return list(self._documents)

    def graph(self) -> dict:
        docs = self.documents()
        by_key: dict[str, DocumentRecord] = {}
        for rec in docs:
            by_key[rec.name.strip().lower()] = rec
            by_key[rec.doc_id.lower()] = rec
        nodes = [
            {"id": r.doc_id, "label": r.name, "ghost": False, "ca": r.tags.is_class_action}
            for r in docs
        ]
        backlinks: dict[str, list[str]] = {r.doc_id: [] for r in docs}
        edges: list[dict] = []
        seen: set[tuple[str, str]] = set()
        ghosts: dict[str, str] = {}
        for rec in docs:
            for target in rec.links:
                key = target.strip().lower()
                resolved = by_key.get(key)
                if resolved is not None:
                    if resolved.doc_id == rec.doc_id:
                        continue
                    pair = (rec.doc_id, resolved.doc_id)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    edges.append({"s": rec.doc_id, "t": resolved.doc_id, "r": True})
                    backlinks[resolved.doc_id].append(rec.doc_id)
                else:
                    ghost = ghosts.get(key)
                    if ghost is None:
                        ghost = f"unresolved-{len(ghosts) + 1}"
                        ghosts[key] = ghost
                        nodes.append(
                            {
                                "id": ghost,
                                "label": target.strip(),
                                "ghost": True,
                                "ca": False,
                            }
                        )
                    pair = (rec.doc_id, ghost)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    edges.append({"s": rec.doc_id, "t": ghost, "r": False})
        return {"nodes": nodes, "edges": edges, "backlinks": backlinks}

    def recall(self, q: str) -> dict:
        query = q.strip().lower()
        docs: list[dict] = []
        for rec in self.documents():
            if query:
                hay = f"{rec.name}\n{rec.text}\n{rec.tags.summary()}".lower()
                if query not in hay:
                    continue
            snippet = ""
            if query:
                idx = rec.text.lower().find(query)
                if idx < 0:
                    snippet = rec.tags.summary().replace("\n", " ")[:160]
                else:
                    start = max(0, idx - 50)
                    end = min(len(rec.text), idx + len(query) + 70)
                    prefix = "..." if start > 0 else ""
                    suffix = "..." if end < len(rec.text) else ""
                    snippet = prefix + " ".join(rec.text[start:end].split()) + suffix
            docs.append({"doc_id": rec.doc_id, "name": rec.name, "snippet": snippet})
        result = self.simulate()
        with self._lock:
            live = [v for values in self._live.values() for v in values[1]]
        candidates = live + [m.violation for m in result.matches + result.review]
        found: list[dict] = []
        seen: set[str] = set()
        for v in candidates:
            if v.id in seen:
                continue
            seen.add(v.id)
            hay = f"{v.id} {v.program} {v.description} {v.source}".lower()
            if query and query not in hay:
                continue
            found.append({"id": v.id, "program": v.program, "source": v.source})
        return {"query": q, "documents": docs, "violations": found}

    def joins(self) -> list[dict]:
        with self._lock:
            return list(self._joins)

    def join_suit(self, violation: Violation) -> dict:
        match = evaluate(violation, SAMPLE_RECORD)
        if match is not None:
            evidence = "\n".join(f"  - {item}" for item in match.evidence)
            confidence = f"{match.confidence:.0%}"
        else:
            evidence = "  - (not auto-matched; verify class membership manually)"
            confidence = "n/a"
        draft = render(
            "class_claim",
            {
                "NOT_LEGAL_ADVICE": NOT_LEGAL_ADVICE,
                "PROGRAM": violation.program,
                "VIOLATION_ID": violation.id,
                "SOURCE": violation.source,
                "PARTY_NAME": SAMPLE_RECORD.party,
                "DATE": date.today().isoformat(),
                "CONFIDENCE": confidence,
                "EVIDENCE": evidence,
            },
        )
        entry = {
            "violation_id": violation.id,
            "program": violation.program,
            "source": violation.source,
            "status": "draft_ready",
            "joined_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "file_by": violation.window_end.isoformat(),
            "matched": match is not None,
            "confidence": round(match.confidence, 3) if match else None,
            "draft": draft,
        }
        with self._lock:
            self._joins.append(entry)
        return entry

    def auto_join(self, violations: list[Violation]) -> dict:
        joined: list[str] = []
        skipped: list[str] = []
        current = {j["violation_id"] for j in self.joins()}
        for v in violations:
            if v.id in current:
                continue
            match = evaluate(v, SAMPLE_RECORD)
            if match is not None and match.confidence >= MIN_AUTO_CONFIDENCE:
                entry = self.join_suit(v)
                entry["auto"] = True
                joined.append(v.id)
            else:
                skipped.append(v.id)
        return {"joined": joined, "skipped": skipped}


class ProseHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    app: WebApp

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if not self.path.startswith("/api/vocabulary/"):
            self.send_header("Access-Control-Allow-Origin", "*")
        else:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _html(self, status: int, text: str) -> None:
        self._send(status, text.encode("utf-8"), "text/html; charset=utf-8")

    def _json(self, status: int, payload: dict | list) -> None:
        self._send(status, (json.dumps(payload, indent=2) + "\n").encode("utf-8"), "application/json")

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[prose.web] {self.address_string()} {fmt % args}", file=sys.stderr)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._html(200, render_dashboard(self.app.simulate()))
            elif path == "/copilot":
                self._html(200, render_copilot_page(
                    PAGE_CSS, NAV, self.app.copilot.status(), self.app.documents()
                ))
            elif path == "/api/copilot/status":
                self._json(200, self.app.copilot.status())
            elif path == "/practice":
                self._html(200, render_practice_page(
                    PAGE_CSS, NAV, self.app.practice.models.status(), self.app.documents()))
            elif path == "/vocabulary":
                self._html(200, render_vocabulary_page(PAGE_CSS, NAV))
            elif path == "/research":
                self._html(200, render_research_page(PAGE_CSS, NAV))
            elif path == "/api/vocabulary/export":
                self._json(200, self.app.vocabulary.export())
            elif path == "/api/vocabulary/anki":
                self._send(200, self.app.vocabulary.anki_text().encode("utf-8"),
                           "text/plain; charset=utf-8")
            elif path == "/api/copilot/events":
                self._copilot_events(params)
            elif path == "/live":
                source, query, limit = _live_params(params)
                self._html(200, render_live_page(source, query, limit, self.app.live(source, query, limit)))
            elif path == "/api/simulate":
                self._json(200, simulate_result_json(self.app.simulate()))
            elif path == "/exports":
                self._html(200, render_exports_page(self.app.simulate()))
            elif path == "/exports/case-file":
                self._html(200, render_case_file_page(self.app.simulate()))
            elif path == "/live.json":
                source, query, limit = _live_params(params)
                violations = self.app.live(source, query, limit)
                self._json(
                    200,
                    {
                        "source": source,
                        "query": query,
                        "limit": limit,
                        "violations": [violation_to_json(v) for v in violations],
                    },
                )
            elif path == "/hud/stream":
                self._sse()
            elif path == "/documents":
                error = params.get("error", [None])[0]
                notice = None
                if "added" in params:
                    added = params.get("added", ["0"])[0]
                    skipped = params.get("skipped", ["0"])[0]
                    notice = (
                        f"loaded {added} case file(s) into the review set "
                        f"({skipped} skipped as duplicates)."
                    )
                elif "import_error" in params:
                    notice = "import failed \u2014 " + params["import_error"][0]
                self._html(
                    200,
                    render_documents_page(
                        self.app.documents(), error, self.app.graph(), notice
                    ),
                )
            elif path == "/recall":
                self._json(200, self.app.recall(params.get("q", [""])[0]))
            elif path == "/graph.json":
                self._json(200, self.app.graph())
            elif path == "/documents.json":
                self._json(
                    200,
                    {"documents": [document_to_json(r) for r in self.app.documents()]},
                )
            elif path == "/suits":
                query = params.get("query", [None])[0] or None
                limit = _clamp_limit(params.get("limit", ["10"])[0])
                suits = self.app.live("recap", query, limit)
                notice = None
                if "auto_joined" in params:
                    done = params.get("auto_joined", ["0"])[0]
                    left = params.get("review_left", ["0"])[0]
                    notice = (
                        f"{done} suit(s) auto-enrolled \u2014 draft joinders "
                        f"ready. {left} below threshold left for review."
                    )
                self._html(
                    200,
                    render_suits_page(query, limit, suits, self.app.joins(), notice),
                )
            elif path == "/suits.json":
                query = params.get("query", [None])[0]
                limit = _clamp_limit(params.get("limit", ["10"])[0])
                out = []
                for v in self.app.live("recap", query, limit):
                    item = violation_to_json(v)
                    m = evaluate(v, SAMPLE_RECORD)
                    item["match"] = None if m is None else match_to_json(m)
                    out.append(item)
                self._json(200, {"query": query, "suits": out})
            elif path == "/joins.json":
                self._json(200, {"joins": self.app.joins()})
            else:
                self._send(404, b'{"error": "not found"}\n', "application/json")
        except OSError:
            pass

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        limit = 16_000_000 if parsed.path == "/api/vocabulary/import" else 1_000_000
        if length < 0 or length > limit:
            self.close_connection = True
            with suppress(OSError):
                self._json(413, {"error": f"body too large ({limit // 1_000_000} MB max)"})
            return
        try:
            body = (
                self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
            )
            if parsed.path.startswith("/api/copilot/"):
                self._copilot_post(parsed.path, body)
                return
            if parsed.path.startswith("/api/practice/"):
                self._practice_post(parsed.path, body)
                return
            if parsed.path.startswith("/api/vocabulary/"):
                self._vocabulary_post(parsed.path, body)
                return
            if parsed.path.startswith("/api/research/"):
                self._research_post(parsed.path, body)
                return
            params = parse_qs(body)
            if parsed.path == "/documents":
                self._handle_document_post(params)
            elif parsed.path == "/documents/sample":
                self._handle_sample_post()
            elif parsed.path == "/suits/join":
                self._handle_join_post(params)
            elif parsed.path == "/suits/auto-join":
                self._handle_auto_join_post(params)
            elif parsed.path == "/import":
                self._handle_import_post(params)
            else:
                self._send(404, b'{"error": "not found"}\n', "application/json")
        except OSError:
            pass
        except (ValueError, KeyError, TypeError) as exc:
            with suppress(OSError):
                self._json(400, {"error": str(exc)})

    def _wants_json(self) -> bool:
        return "application/json" in (self.headers.get("Accept") or "")

    def _research_post(self, path: str, body: str) -> None:
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            self._json(403, {"error": "cross-origin research requests are not allowed"})
            return
        if self.headers.get_content_type() != "application/json":
            self._json(415, {"error": "use application/json"})
            return
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        try:
            if path == "/api/research/catalog":
                result = self.app.research.catalog()
            elif path == "/api/research/import-case":
                result = import_case_folder(self.app.research)
            elif path == "/api/research/search":
                result = self.app.research.search(data.get("query", ""),
                                                  data.get("category", ""),
                                                  offset=data.get("offset", 0))
            elif path == "/api/research/document":
                result = self.app.research.document(data.get("source_id"))
            else:
                self._json(404, {"error": "not found"})
                return
            self._json(200, result)
        except KeyError:
            self._json(404, {"error": "Research source not found"})
        except sqlite3.Error:
            self._json(503, {"error": "Research library is temporarily unavailable. Retry shortly."})

    def _vocabulary_post(self, path: str, body: str) -> None:
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            self._json(403, {"error": "cross-origin vocabulary requests are not allowed"})
            return
        if self.headers.get_content_type() != "application/json":
            self._json(415, {"error": "use application/json"})
            return
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        store = self.app.vocabulary
        handlers = {"list": lambda: store.listing(), "lookup": lambda: store.lookup(data.get("word")),
                    "library": lambda: store.library(data),
                    "save": lambda: store.save(data), "review": lambda: store.review(data),
                    "settings": lambda: store.settings(data), "import": lambda: store.import_backup(data)}
        handler = handlers.get(path.removeprefix("/api/vocabulary/"))
        if handler is None:
            self._json(404, {"error": "not found"})
            return
        try:
            self._json(200, handler())
        except VocabularyConflict as exc:
            self._json(409, {"error": str(exc)})
        except KeyError:
            self._json(404, {"error": "word not found"})
        except sqlite3.Error:
            self._json(503, {"error": "The word notebook could not be saved. Retry in a moment."})

    def _practice_post(self, path: str, body: str) -> None:
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            self._json(403, {"error": "cross-origin practice requests are not allowed"})
            return
        if self.headers.get_content_type() != "application/json":
            self._json(415, {"error": "use application/json"})
            return
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        try:
            if path == "/api/practice/sessions":
                self._json(201, self.app.practice.create(data, self.app.documents()))
            elif path in ("/api/practice/turn", "/api/practice/state", "/api/practice/stop",
                          "/api/practice/model"):
                session_id = data.get("session_id")
                if not isinstance(session_id, str) or not session_id:
                    raise ValueError("session_id is required")
                if path.endswith("/stop"):
                    self.app.practice.stop(session_id)
                    self._json(200, {"stopped": True})
                else:
                    session = self.app.practice.get(session_id)
                    if path.endswith("/model"):
                        from .copilot import ModelCoach

                        model_id, settings = self.app.practice.models.resolve(data.get("model_id"))
                        state = session.change_model(
                            model_id, ModelCoach(settings, max_completion_tokens=4096),
                            data.get("expected_turn"))
                    elif path.endswith("/turn"):
                        state = session.reply(data.get("text"), data.get("expected_turn"))
                    else:
                        state = session.snapshot()
                    self._json(200, state)
            else:
                self._json(404, {"error": "not found"})
        except DebateConflict as exc:
            self._json(409, {"error": str(exc)})
        except KeyError:
            self._json(404, {"error": "Practice not found or expired. Start a new debate."})
        except CopilotError as exc:
            self._json(503, {"error": str(exc)})

        except sqlite3.Error:
            self._json(503, {"error": "Vocabulary progress could not be saved. Retry this turn."})

    def _copilot_post(self, path: str, body: str) -> None:
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            self._json(403, {"error": "cross-origin session requests are not allowed"})
            return
        if self.headers.get_content_type() != "application/json":
            self._json(415, {"error": "use application/json"})
            return
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        try:
            if path == "/api/copilot/sessions":
                session_id, session = self.app.copilot.create(data, self.app.documents())
                self._json(201, {"session_id": session_id, "mode": session.config.mode})
            elif path in ("/api/copilot/turn", "/api/copilot/stop"):
                session_id = data.get("session_id")
                if not isinstance(session_id, str) or not session_id:
                    raise ValueError("session_id is required")
                if path.endswith("/stop"):
                    self.app.copilot.stop(session_id)
                    self._json(200, {"stopped": True})
                else:
                    session = self.app.copilot.get(session_id)
                    frame = session.feed_transcript(TranscriptLine(
                        data.get("speaker", "Speaker"), data.get("text", "")
                    ))
                    self._json(200, {"frame": frame_to_payload(frame)})
            else:
                self._json(404, {"error": "not found"})
        except KeyError:
            self._json(404, {"error": "session not found or expired"})
        except CopilotError as exc:
            self._json(503, {"error": str(exc)})

    def _copilot_events(self, params: dict[str, list[str]]) -> None:
        session_id = params.get("session_id", [""])[0]
        serialize = (
            frame_to_glasses_payload if params.get("view", [""])[0] == "glasses"
            else frame_to_payload
        )
        try:
            session = self.app.copilot.get(session_id)
        except KeyError:
            self._json(404, {"error": "session not found or expired"})
            return
        try:
            seq = max(0, int(self.headers.get("Last-Event-ID", "0")))
        except ValueError:
            seq = 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            while not session.closed:
                if time.monotonic() - session.last_activity > 1800:
                    self.app.copilot.stop(session_id)
                    break
                frames = session.frames_after(seq, wait=10)
                # Reconnect to the current state instead of flashing stale cues.
                if frames:
                    frame = frames[-1]
                    seq = frame.seq
                    payload = json.dumps(serialize(frame))
                    self.wfile.write(f"id: {seq}\nevent: frame\ndata: {payload}\n\n".encode())
                else:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
            self.wfile.write(b"event: stopped\ndata: {}\n\n")
            self.wfile.flush()
        except OSError:
            return

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _handle_document_post(self, params: dict[str, list[str]]) -> None:
        name = params.get("name", [""])[0]
        text = params.get("text", [""])[0]
        if not text.strip():
            if self._wants_json():
                raise ValueError("text is required")
            self._redirect("/documents?error=empty")
            return
        rec = self.app.add_document(name, text)
        if self._wants_json():
            self._json(200, document_to_json(rec))
        else:
            self._redirect("/documents")

    def _handle_sample_post(self) -> None:
        for name, text in SAMPLE_DOCS:
            self.app.add_document(name, text)
        if self._wants_json():
            self._json(201, {"added": len(SAMPLE_DOCS)})
        else:
            self._redirect("/documents")

    def _handle_join_post(self, params: dict[str, list[str]]) -> None:
        raw = params.get("violation", [""])[0]
        if not raw:
            raise ValueError("violation payload is required")
        violation = violation_from_json(json.loads(html.unescape(raw)))
        entry = self.app.join_suit(violation)
        if self._wants_json():
            self._json(201, entry)
        else:
            self._redirect("/suits")

    def _handle_auto_join_post(self, params: dict[str, list[str]]) -> None:
        query = params.get("query", [""])[0] or None
        limit = _clamp_limit(params.get("limit", ["10"])[0])
        suits = self.app.live("recap", query, limit)
        result = self.app.auto_join(suits)
        self._redirect(
            "/suits?"
            + urlencode(
                {
                    "query": query or "",
                    "limit": str(limit),
                    "auto_joined": str(len(result["joined"])),
                    "review_left": str(len(result["skipped"])),
                }
            )
        )

    def _handle_import_post(self, params: dict[str, list[str]]) -> None:
        raw = params.get("path", [""])[0]
        try:
            result = self.app.import_path(raw)
        except ValueError as exc:
            if self._wants_json():
                raise
            self._redirect("/documents?" + urlencode({"import_error": str(exc)}))
            return
        if self._wants_json():
            self._json(200, result)
        else:
            self._redirect("/documents?" + urlencode(result))

    def _sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        hud = HudSimulator()
        for line in SAMPLE_TRANSCRIPT:
            frame = hud.feed(line)
            payload = json.dumps(frame_to_payload(frame))
            try:
                self.wfile.write(f"event: frame\ndata: {payload}\n\n".encode())
                self.wfile.flush()
            except OSError:
                return
            time.sleep(0.8)


@dataclass
class WebSite:
    server: ThreadingHTTPServer
    app: WebApp

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self.server.serve_forever()


def build_site(host: str, port: int, app: WebApp | None = None) -> WebSite:
    app = app or WebApp()

    class _Handler(ProseHandler):
        pass

    _Handler.app = app

    class _Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

        def server_close(self) -> None:
            app.copilot.close()
            app.practice.close()
            super().server_close()

    server = _Server((host, port), _Handler)
    return WebSite(server, app)


def serve(host: str = "127.0.0.1", port: int = 8000, block: bool = True) -> WebSite:
    site = build_site(host, port)
    print(f"[prose.web] dashboard    : {site.url}")
    print(f"[prose.web] live coach   : {site.url}/copilot (litigation + debate)")
    print(f"[prose.web] practice     : {site.url}/practice (AI opponent + private coach)")
    print(f"[prose.web] vocabulary   : {site.url}/vocabulary (saved word notebook + recall)")
    print(f"[prose.web] discovery    : {site.url}/documents (recall + graph)")
    print(f"[prose.web] collections  : {site.url}/live")
    print(f"[prose.web] class actions: {site.url}/suits")
    print(f"[prose.web] HUD stream   : {site.url}/hud/stream (SSE)")
    print(
        f"[prose.web] exports      : {site.url}/api/simulate, "
        f"/recall, /graph.json, /live.json"
    )
    if block:
        site.start()
    return site
