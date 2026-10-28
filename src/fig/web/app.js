'use strict';
const $ = (id) => document.getElementById(id);
const state = {companies:[], selected:null, relationships:[], entities:new Map(), documents:[], generation:0, searchGeneration:0, pathGeneration:0, evidenceGeneration:0, nextOffset:null, searchQuery:'', activeClaim:null};
const predicateLabels = {CONTRACTS_MANUFACTURING_TO:'Manufacturing contracted to', SUPPLIES_TO:'Supplies to', MANUFACTURES:'Manufactures', DEVELOPS:'Develops', USES_TECHNOLOGY:'Uses technology', PARTNERS_WITH:'Partners with', COMPETES_WITH:'Competes with', OWNS:'Owns', CEO_OF:'CEO of'};
function element(tag, className, text) { const node=document.createElement(tag); if(className)node.className=className; if(text!==undefined)node.textContent=text; return node; }
function setNotice(id, text) { $(id).textContent=text; $(id).hidden=!text; }
function sourceDate(value) { if(!value)return 'Unknown'; return new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'America/New_York'}).format(new Date(value)); }
function safeSourceLink(value) { try {const url=new URL(value); return url.protocol==='https:'?url.href:null;}catch{return null;} }
async function api(path, body) {
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),path==='/v1/extraction/runs'?90000:20000);
  try {
    const response=await fetch(path,{signal:controller.signal,...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
    if(!response.ok){
      const problem=await response.json().catch(()=>({}));
      const message=Array.isArray(problem.detail)?problem.detail.map(item=>item.msg).join('; '):problem.detail?.message;
      throw new Error(message||(response.status===503?'The data service is unavailable. Check local configuration and migrations, then retry.':`Unable to load data (${response.status}). Please retry.`));
    }
    return await response.json();
  }catch(error){
    if(error.name==='AbortError')throw new Error('The request timed out. Check the local server, then retry. For a review action, refresh the queue before retrying to check whether it was saved.');
    if(error instanceof TypeError)throw new Error('Cannot reach the local server. Check that it is running, then retry.');
    throw error;
  }finally{clearTimeout(timeout);}
}
function entityName(id) {return state.entities.get(id)?.canonical_name||'Unknown company';}
function relationSubject(relation){return relation.resolved_subject_id||relation.claim.subject_id;}
function relationObject(relation){return relation.resolved_object_id||relation.claim.object_id;}
function label(predicate) {return predicateLabels[predicate]||predicate.replaceAll('_',' ').toLowerCase();}
function latestRelationships(relations){const latest=new Map();for(const relation of relations){const key=[relationSubject(relation),relation.claim.predicate,relationObject(relation)].join('|');const date=relation.evidence[0]?.document?.published_at||relation.claim.source_available_at;const previous=latest.get(key);const previousDate=previous?.evidence[0]?.document?.published_at||previous?.claim?.source_available_at;if(!previous||date>previousDate)latest.set(key,relation);}return Array.from(latest.values());}
function resetEvidence() {state.evidenceGeneration++; state.activeClaim=null; $('close-evidence').hidden=true; $('evidence-title').textContent='Read the source'; const box=$('evidence-content');box.replaceChildren();const inner=element('div','evidence-empty');inner.append(element('div','paper-icon','≡'),element('h3',null,'The source is one click away.'),element('p',null,'Select a relationship in the map to inspect its supporting quote, filing, and review status.'),element('div','evidence-principle','Source statement → reviewed claim → relationship'));box.append(inner);document.querySelectorAll('.edge-button').forEach(b=>b.classList.remove('active'));}
function resetSearch() {state.searchGeneration++;state.nextOffset=null;state.searchQuery='';$('query').value='';$('search-results').replaceChildren();$('search-status').textContent='Search returns original passages. Results are not automatically accepted as claims.';$('load-more').hidden=true;$('search-button').disabled=false;}
async function loadCompanies(discoverDemo=false) {
  const previous=state.selected?.id;
  $('refresh').disabled=true;$('include-demo').disabled=true;$('company').disabled=true;setNotice('global-error','');setNotice('corpus-notice','');
  try {
    const real=await api('/v1/entities?limit=100&include_synthetic=false');
    let data=$('include-demo').checked?await api('/v1/entities?limit=100&include_synthetic=true'):real;
    if(discoverDemo&&!real.entities.length&&!data.entities.length){
      const demo=await api('/v1/entities?limit=100&include_synthetic=true');
      if(demo.entities.length){data=demo;$('include-demo').checked=true;}
    }
    $('demo-notice').hidden=!$('include-demo').checked;
    state.companies=data.entities;$('company').replaceChildren();
    if(!data.entities.length){$('company').append(element('option',null,'No companies in the corpus'));state.generation++;state.selected=null;state.entities=new Map();state.relationships=[];state.documents=[];renderGraph();renderDocuments();resetEvidence();resetSearch();resetPaths();clearCandidates();$('ask-button').disabled=true;$('search-button').disabled=true;$('data-mode').textContent='EMPTY WORKSPACE';['relationship-count','counterparty-count','source-count'].forEach(id=>$(id).textContent='0');setNotice('corpus-notice','No companies are visible. Run fig demo and Refresh data, include an existing synthetic demo, or ingest SEC filings using the Get started guide.');$('getting-started').open=true;return;}
    const realIds=new Set(real.entities.map(company=>company.id));
    for(const company of data.entities){const option=element('option',null,company.canonical_name+(realIds.has(company.id)?'':' · synthetic'));option.value=company.id;$('company').append(option);}
    $('ask-button').disabled=false;
    if(!real.entities.length&&!previous)$('ask-question').value='Show paths between Example Designer and Example Customer';
    const chosen=data.entities.find(e=>e.id===previous)||(!real.entities.length&&data.entities.find(e=>e.canonical_name==='Example Designer'))||data.entities[0];$('company').value=chosen.id;$('company').disabled=false;
    await selectCompany(chosen.id);
    if(data.truncated)setNotice('global-error','The selector shows the first 100 companies in this corpus.');
  }catch(error){state.generation++;state.selected=null;state.companies=[];state.relationships=[];state.documents=[];resetPaths();resetEvidence();resetSearch();renderGraph();renderDocuments();clearCandidates();$('ask-button').disabled=true;$('search-button').disabled=true;setNotice('global-error',error.message);$('company').replaceChildren(element('option',null,'Companies unavailable'));}
  finally{$('refresh').disabled=false;$('include-demo').disabled=false;}
}
async function selectCompany(id) {
  const generation=++state.generation;state.selected=state.companies.find(e=>e.id===id);state.relationships=[];state.entities=new Map(state.companies.map(e=>[e.id,e]));state.documents=[];
  resetEvidence();resetSearch();resetPaths();$('graph').replaceChildren(element('div','empty','Loading reviewed relationships…'));$('graph-title').textContent=state.selected.canonical_name;setNotice('graph-note','');setNotice('global-error','');['relationship-count','counterparty-count','source-count'].forEach(id=>$(id).textContent='—');renderDocuments();clearCandidates();
  try {
    const [neighbors,corpus]=await Promise.all([api('/v1/graph/neighbors',{entity_id:id,limit:100}),api('/v1/documents?limit=100')]);
    if(generation!==state.generation)return;
    state.relationships=latestRelationships(neighbors.relationships);for(const entity of neighbors.entities)state.entities.set(entity.id,entity);
    const documents=new Map(corpus.documents.filter(d=>d.issuer_id===id&&($('include-demo').checked||d.source==='sec')).map(d=>[d.id,d]));
    for(const relation of neighbors.relationships)for(const evidence of relation.evidence)documents.set(evidence.document.id,evidence.document);
    state.documents=Array.from(documents.values());
    $('data-mode').textContent=state.documents.length&&state.documents.every(doc=>doc.source!=='sec')?'SYNTHETIC DEMO':'SEC DOCUMENTS';
    $('relationship-count').textContent=String(state.relationships.length)+(neighbors.truncated?'+':'');
    $('counterparty-count').textContent=new Set(state.relationships.map(r=>relationSubject(r)===neighbors.canonical_entity_id?relationObject(r):relationSubject(r))).size;
    $('source-count').textContent=new Set(neighbors.relationships.flatMap(r=>r.evidence.map(e=>e.document.id))).size;
    renderGraph();renderDocuments();
    if(state.relationships.length)void openRelationship(state.relationships[0]);
    if(neighbors.truncated)setNotice('graph-note','The result is capped at 100 relationships.');
    else if(state.relationships.length>8)setNotice('graph-note','The map shows the first eight relationships. Coverage counts include all loaded relationships.');
    else if(corpus.truncated)setNotice('graph-note','The source selector includes the first 100 corpus documents and all filings cited by these relationships.');
    await loadDocumentMetadata();await loadCandidates();
  }catch(error){if(generation!==state.generation)return;setNotice('global-error',error.message);$('graph').replaceChildren(element('div','empty','Relationships could not be loaded. Use Refresh data to retry.'));}
}
function resetPaths(){
  state.pathGeneration++;$('path-results').replaceChildren();const target=$('path-target');target.replaceChildren();
  const choices=state.companies.filter(company=>company.id!==state.selected?.id);
  for(const company of choices){const option=element('option',null,company.canonical_name);option.value=company.id;target.append(option);}
  target.disabled=!choices.length;$('find-paths').disabled=!choices.length;$('path-status').textContent=choices.length?'Choose a target company to find evidence-backed paths.':'No other companies are available in this corpus.';
}
async function findPaths(){
  if(!state.selected||$('path-target').disabled)return;const generation=++state.pathGeneration;
  $('find-paths').disabled=true;$('path-results').replaceChildren();$('path-status').textContent='Searching accepted claims…';
  try{
    const result=await api('/v1/graph/paths',{source_entity_id:state.selected.id,target_entity_id:$('path-target').value,min_hops:1,max_hops:Number($('path-hops').value),direction:'both',limit:20});
    if(generation!==state.pathGeneration)return;for(const entity of result.entities)state.entities.set(entity.id,entity);
    if(!result.paths.length){$('path-status').textContent='No supported path exists within this hop limit. Missing relationships remain a visible coverage gap.';return;}
    $('path-status').textContent=`${result.paths.length} supported path${result.paths.length===1?'':'s'} found${result.truncated?' · result limit reached':''}. Select any edge to inspect its filing evidence.`;
    result.paths.forEach((path,index)=>{
      const card=element('article','path-card');card.append(element('div','path-number',`PATH ${index+1} · ${path.hops} HOP${path.hops===1?'':'S'}`));
      const chain=element('div','path-chain');path.entity_ids.forEach((id,nodeIndex)=>{chain.append(element('span','path-node',entityName(id)));if(nodeIndex<path.edges.length){const edge=path.edges[nodeIndex];const button=element('button','path-edge',`${edge.traversal==='reverse'?'←':'→'} ${label(edge.claim.predicate)} · evidence`);button.type='button';button.addEventListener('click',()=>openRelationship(edge));chain.append(button);}});card.append(chain);$('path-results').append(card);
    });
  }catch(error){if(generation===state.pathGeneration)$('path-status').textContent=error.message;}
  finally{if(generation===state.pathGeneration)$('find-paths').disabled=$('path-target').disabled;}
}
async function askResearch(event){
  event.preventDefault();const question=$('ask-question').value.trim();if(question.length<5){$('ask-status').textContent='Enter a question naming at least one registered company.';return;}
  $('ask-button').disabled=true;$('ask-results').replaceChildren();$('ask-status').textContent='Resolving entities and verifying bounded graph paths…';
  try{const result=await api('/v1/research/ask',{question,max_hops:Number($('ask-hops').value),limit:20});for(const entity of result.entities)state.entities.set(entity.id,entity);for(const entity of result.resolved_entities)state.entities.set(entity.id,entity);
    const answer=element('div','ask-answer');answer.append(element('span','badge reviewed',result.verification.status.replaceAll('_',' ')),element('h3',null,result.answer),element('p','muted',result.limitations));$('ask-results').append(answer);
    result.paths.forEach((path,index)=>{const card=element('article','path-card');card.append(element('div','path-number',`VERIFIED PATH ${index+1} · ${path.hops} HOP${path.hops===1?'':'S'}`));const chain=element('div','path-chain');path.entity_ids.forEach((id,nodeIndex)=>{chain.append(element('span','path-node',entityName(id)));if(nodeIndex<path.edges.length){const edge=path.edges[nodeIndex];const button=element('button','path-edge',`${edge.traversal==='reverse'?'←':'→'} ${label(edge.claim.predicate)} · evidence`);button.type='button';button.addEventListener('click',()=>openRelationship(edge));chain.append(button);}});card.append(chain);$('ask-results').append(card);});
    const details=element('details','cypher-details');const summary=element('summary',null,'Inspect query plan and read-only Cypher');const pre=element('pre',null,result.generated_cypher+'\n\nParameters\n'+JSON.stringify(result.cypher_parameters,null,2));details.append(summary,pre);$('ask-results').append(details);$('ask-status').textContent=`${result.verification.path_count} verified paths · ${result.verification.citation_count} source citations. ${result.execution}`;
  }catch(error){$('ask-status').textContent=error.message;}finally{$('ask-button').disabled=false;}
}
function renderGraph() {
  const graph=$('graph');graph.replaceChildren();
  if(!state.relationships.length){graph.style.height='320px';graph.append(element('div','empty','No accepted source-supported relationships are available for this company yet.'));return;}
  const relations=state.relationships.slice(0,8);const available=graph.parentElement.clientWidth;const vertical=available<610&&relations.length===1;graph.style.minWidth=vertical?'0':'610px';const width=vertical?available:Math.max(610,available);const height=vertical?430:Math.max(320,relations.length*145+60);graph.style.height=height+'px';
  const ns='http://www.w3.org/2000/svg';const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('aria-hidden','true');
  const defs=document.createElementNS(ns,'defs');const marker=document.createElementNS(ns,'marker');for(const [key,value]of Object.entries({id:'arrow',viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'5',markerHeight:'5',orient:'auto-start-reverse'}))marker.setAttribute(key,value);const triangle=document.createElementNS(ns,'path');triangle.setAttribute('d','M 0 0 L 10 5 L 0 10 z');triangle.setAttribute('fill','#8ca977');marker.append(triangle);defs.append(marker);svg.append(defs);graph.append(svg);
  const center=height/2;const selected=element('div','node selected');selected.style.left=(vertical?(width-172)/2:24)+'px';selected.style.top=(vertical?40:center-48)+'px';if(vertical)selected.style.minHeight='96px';selected.append(element('span','node-kicker','SELECTED COMPANY'),element('span',null,state.selected.canonical_name));graph.append(selected);
  relations.forEach((relation,index)=>{
    const subject=relationSubject(relation),object=relationObject(relation);const outgoing=subject===state.selected.id;const other=outgoing?object:subject;const y=relations.length===1?center:75+index*145;
    const node=element('div','node');node.style.left=(vertical?(width-172)/2:width-196)+'px';node.style.top=(vertical?282:y-48)+'px';node.append(element('span','node-kicker','COMPANY'),element('span',null,entityName(other)));graph.append(node);
    const path=document.createElementNS(ns,'path');const xLeft=196,xRight=width-196,mid=width/2;path.setAttribute('d',vertical?(outgoing?`M ${mid} 136 L ${mid} 282`:`M ${mid} 282 L ${mid} 136`):(outgoing?`M ${xLeft} ${center} C ${mid} ${center},${mid} ${y},${xRight} ${y}`:`M ${xRight} ${y} C ${mid} ${y},${mid} ${center},${xLeft} ${center}`));path.setAttribute('fill','none');path.setAttribute('stroke','#a7bc94');path.setAttribute('stroke-width','1.6');path.setAttribute('marker-end','url(#arrow)');svg.append(path);
    const button=element('button','edge-button');button.type='button';button.style.left=(mid-82)+'px';button.style.top=(vertical?185:(center+y)/2-23)+'px';button.dataset.claim=relation.claim.id;button.setAttribute('aria-label',`${entityName(subject)} ${label(relation.claim.predicate)} ${entityName(object)}. Open supporting evidence.`);button.append(element('span',null,label(relation.claim.predicate)),element('small',null,'View evidence ↗'));button.addEventListener('click',()=>openRelationship(relation));if(state.activeClaim===relation.claim.id)button.classList.add('active');graph.append(button);
  });
}
function renderDocuments() {
  const select=$('document');select.replaceChildren();
  if(!state.documents.length){select.append(element('option',null,'No source filing available'));select.disabled=true;$('query').disabled=true;$('search-button').disabled=true;$('passage-count').textContent='';updateComparisonDocuments();clearCandidates();return;}
  for(const doc of state.documents){const option=element('option',null,`${doc.form} · ${sourceDate(doc.published_at)}${doc.issuer_id!==state.selected?.id?' · cited counterparty filing':''}`);option.value=doc.id;select.append(option);}
  select.disabled=false;$('query').disabled=false;$('search-button').disabled=false;updateComparisonDocuments();
}
function updateComparisonDocuments(){
  const comparison=$('compare-document');comparison.replaceChildren();$('comparison-results').replaceChildren();
  const choices=state.documents.filter(document=>document.id!==$('document').value&&document.issuer_id===state.selected?.id);
  for(const document of choices){const option=element('option',null,`${document.form} · ${sourceDate(document.published_at)} · ${document.accession}`);option.value=document.id;comparison.append(option);}
  comparison.disabled=!choices.length;$('compare-filings').disabled=!choices.length;$('comparison-status').textContent=choices.length?'Enter a phrase to compare exact passages across filings.':'No second filing for this issuer is available.';
}
async function compareFilings(){
  const query=$('compare-query').value.trim();if(query.length<2){$('comparison-status').textContent='Enter at least two characters to compare.';return;}
  $('compare-filings').disabled=true;$('comparison-results').replaceChildren();$('comparison-status').textContent='Comparing dated filing passages…';
  try{
    const data=await api('/v1/documents/compare',{left_document_id:$('compare-document').value,right_document_id:$('document').value,query,limit:10});
    $('comparison-status').textContent=`${data.left_match_count} earlier and ${data.right_match_count} later matches. Wording classifications require source review.`;
    for(const pair of data.pairs){const card=element('article','comparison-card');card.append(element('span','badge neutral',pair.classification),element('span','similarity',pair.similarity===null?'unpaired':Math.round(pair.similarity*100)+'% similar'));
      const columns=element('div','comparison-columns');for(const [side,item,document] of [['Earlier',pair.left,data.left_document],['Later',pair.right,data.right_document]]){const column=element('div','comparison-side');column.append(element('div','label-small',`${side} · ${document.form} · ${sourceDate(document.published_at)}`));if(item){const button=element('button','passage-result');button.type='button';button.append(element('span','result-section',item.section_path),element('p',null,item.text),element('span','result-open','Open full passage ↗'));button.addEventListener('click',()=>openPassage(item.id));column.append(button);}else column.append(element('p','muted','No paired passage.'));columns.append(column);}card.append(columns);$('comparison-results').append(card);}
  }catch(error){$('comparison-status').textContent=error.message;}
  finally{$('compare-filings').disabled=$('compare-document').disabled;}
}
async function loadDocumentMetadata() {
  const id=$('document').value;const generation=state.generation;if(!id)return;
  $('passage-count').textContent='';
  try{const document=await api('/v1/documents/'+id);if(generation!==state.generation||$('document').value!==id)return;const count=document.text_versions.reduce((total,v)=>total+v.passage_count,0);$('passage-count').textContent=count.toLocaleString()+' passages';}
  catch{if(generation===state.generation&&$('document').value===id)$('passage-count').textContent='Coverage unavailable';}
}
async function runSearch(append=false) {
  if($('document').disabled)return;
  const query=append?state.searchQuery:$('query').value.trim();if(!query){$('search-status').textContent='Enter a company, product, or phrase to search the filing.';return;}
  const generation=++state.searchGeneration;const companyGeneration=state.generation;const documentId=$('document').value;const offset=append?state.nextOffset:0;
  if(append&&offset===null)return;
  if(!append)$('search-results').replaceChildren();state.searchQuery=query;state.nextOffset=null;$('load-more').hidden=true;$('search-button').disabled=true;$('search-status').textContent='Searching the filing…';
  try {
    const params=new URLSearchParams({query,limit:'5',offset:String(offset)});const data=await api(`/v1/documents/${documentId}/passages?${params}`);
    if(generation!==state.searchGeneration||companyGeneration!==state.generation||documentId!==$('document').value)return;
    for(const passage of data.passages){const button=element('button','passage-result');button.type='button';button.append(element('span','result-section',passage.section_path),element('p',null,snippet(passage.text,query)),element('span','result-open','Open original passage ↗'));button.addEventListener('click',()=>openPassage(passage.id));$('search-results').append(button);}
    state.nextOffset=data.next_offset;$('load-more').hidden=!data.truncated;const count=$('search-results').children.length;$('search-status').textContent=count?`${count} passage${count===1?'':'s'} shown${data.truncated?' · more available':''}. Search matches do not establish relationships.`:'No passages match this phrase. Try another company name or a shorter term.';
  }catch(error){if(generation===state.searchGeneration)$('search-status').textContent=error.message;}
  finally{if(generation===state.searchGeneration)$('search-button').disabled=false;}
}
function snippet(text,query){const index=text.toLowerCase().indexOf(query.toLowerCase());const start=Math.max(0,index-80);const end=Math.min(text.length,start+270);return(start?'…':'')+text.slice(start,end)+(end<text.length?'…':'');}
function detailsRow(list,name,value){const row=element('div','detail-row');row.append(element('dt',null,name),element('dd',null,value));list.append(row);}
function drawerBase(title){$('close-evidence').hidden=false;$('evidence-title').textContent=title;const body=element('div','evidence-body');$('evidence-content').replaceChildren(body);return body;}
function sourceDetails(body,doc){const list=element('dl','evidence-details');detailsRow(list,'Filing',doc.form);detailsRow(list,'Published',sourceDate(doc.published_at)+(doc.publication_precision==='date'?' · date precision':''));detailsRow(list,'Accession',doc.accession);detailsRow(list,'Source',doc.source==='sec'?'SEC EDGAR':'Synthetic fixture');body.append(list);const url=safeSourceLink(doc.source_url);if(url&&doc.source==='sec'){const anchor=element('a','source-link','Open source filing ↗');anchor.href=url;anchor.target='_blank';anchor.rel='noopener noreferrer';body.append(anchor);}}
function contextParagraph(body,passage,evidence=null){body.append(element('div','label-small','Surrounding passage'));const text=element('div','passage-context');if(evidence){const chars=Array.from(passage.text);const start=evidence.start_offset-passage.start_offset;const end=evidence.end_offset-passage.start_offset;if(start>=0&&end<=chars.length&&chars.slice(start,end).join('')===evidence.quote){text.append(document.createTextNode(chars.slice(0,start).join('')),element('mark',null,chars.slice(start,end).join('')),document.createTextNode(chars.slice(end).join('')));}else{text.textContent=passage.text;body.append(element('div','caveat','The quote could not be highlighted in this passage version.'));}}else text.textContent=passage.text;body.append(text);}
async function openRelationship(relation) {
  const generation=++state.evidenceGeneration;state.activeClaim=relation.claim.id;document.querySelectorAll('.edge-button').forEach(b=>b.classList.toggle('active',b.dataset.claim===relation.claim.id));
  const body=drawerBase('Relationship evidence');const selected=relation.evidence[0];const claim=relation.claim;
  body.append(element('span','badge reviewed','Reviewed · '+selected.evidence.assessment),element('h3',null,`${entityName(relationSubject(relation))} → ${entityName(relationObject(relation))}`),element('div','muted',label(claim.predicate)),element('div','label-small','Exact source quote'),element('blockquote','source-quote',selected.evidence.quote));
  const review=element('dl','evidence-details');detailsRow(review,'Claim type',claim.assertion_class==='normalized_explicit'?'Normalized source statement':'Explicit source statement');detailsRow(review,'Reviewer',claim.reviewer||'Not recorded');detailsRow(review,'Validity',relation.validity_known?'Effective dates recorded':'Effective dates not established');detailsRow(review,'Evidence',`${relation.evidence.length} supporting passage${relation.evidence.length===1?'':'s'}`);body.append(review);sourceDetails(body,selected.document);
  body.append(element('div','label-small',selected.passage.section_path));const loading=element('div','muted','Loading passage context…');body.append(loading);
  try{const passage=await api('/v1/passages/'+selected.passage.id);if(generation!==state.evidenceGeneration)return;loading.remove();contextParagraph(body,passage,selected.evidence);}
  catch(error){if(generation===state.evidenceGeneration)loading.textContent=error.message;}
  if(generation!==state.evidenceGeneration)return;
  body.append(element('div','label-small','Reviewed disclosure history'));const historyBox=element('div','relationship-history');historyBox.append(element('p','muted','Loading reviewed filings…'));body.append(historyBox);
  try{const history=await api('/v1/relationships/history',{subject_id:relationSubject(relation),object_id:relationObject(relation),predicate:claim.predicate});if(generation!==state.evidenceGeneration)return;historyBox.replaceChildren();const timeline=history.timelines[0];if(!timeline){historyBox.append(element('p','muted','No reviewed history is available.'));}else{for(const event of timeline.events){const item=element('div','history-event');item.append(element('span','badge neutral',event.classification.replace('_',' ')),element('strong',null,sourceDate(event.document.published_at)),element('p',null,event.evidence.quote));historyBox.append(item);}historyBox.append(element('div','caveat',history.interpretation));}}
  catch(error){if(generation===state.evidenceGeneration)historyBox.replaceChildren(element('p','muted',error.message));}
  if(generation!==state.evidenceGeneration)return;
  body.append(element('div','caveat','The relationship is a reviewed normalization of this statement. It does not establish exclusivity, dependency magnitude, or financial materiality.'));
  if(window.innerWidth<=900)$('evidence-title').scrollIntoView({behavior:'smooth',block:'start'});
}
async function openPassage(id) {
  const generation=++state.evidenceGeneration;state.activeClaim=null;document.querySelectorAll('.edge-button').forEach(b=>b.classList.remove('active'));const body=drawerBase('Source passage');body.append(element('p','muted','Loading original passage…'));
  try{const passage=await api('/v1/passages/'+id);if(generation!==state.evidenceGeneration)return;body.replaceChildren();body.append(element('span','badge neutral','Source text · not a reviewed claim'),element('h3',null,passage.section_path));sourceDetails(body,passage.document);contextParagraph(body,passage);body.append(element('div','caveat','A search result is an original passage. It has not automatically become an accepted relationship.'));if(window.innerWidth<=900)$('evidence-title').scrollIntoView({behavior:'smooth',block:'start'});}
  catch(error){if(generation===state.evidenceGeneration){body.replaceChildren(element('p','muted',error.message));}}
}
const reviewState={generation:0,nextOffset:null,entities:[],candidates:[],busy:false,configured:false};
function clearCandidates(){reviewState.generation++;reviewState.candidates=[];reviewState.nextOffset=null;$('candidate-list').replaceChildren();$('more-candidates').hidden=true;$('extract-candidates').disabled=$('document').disabled||reviewState.busy;}
async function loadCandidates(append=false){
  const documentId=$('document').value;const filter=$('candidate-state').value;const offset=append?reviewState.nextOffset:0;const generation=++reviewState.generation;
  if(!append){reviewState.candidates=[];$('candidate-list').replaceChildren();}if($('document').disabled){$('review-status').textContent='Select a source filing to review candidates.';return;}
  $('extract-candidates').disabled=reviewState.busy;$('more-candidates').hidden=true;
  try{const data=await api(`/v1/documents/${documentId}/candidates?state=${filter}&limit=20&offset=${offset}`);if(generation!==reviewState.generation||documentId!==$('document').value)return;reviewState.entities=data.entities;reviewState.candidates.push(...data.candidates);reviewState.nextOffset=data.next_offset;$('more-candidates').hidden=!data.truncated;
    for(const candidate of data.candidates){const card=element('button','passage-result candidate-card');card.type='button';card.append(element('span','badge '+(candidate.state==='accepted'?'reviewed':'neutral'),candidate.state==='duplicate'?'Already recorded':candidate.state),element('h3',null,candidate.counterparty_name),element('p',null,label(candidate.predicate)),element('small','muted',candidate.provider==='rules'?'Foundry rule proposal':`Model proposal · ${candidate.model}`),element('span','result-open','Inspect and review ↗'));card.addEventListener('click',()=>openCandidate(candidate));$('candidate-list').append(card);}
    $('review-status').textContent=reviewState.candidates.length?`${reviewState.candidates.length} candidates shown${data.truncated?' · more available':''}.`:'No candidates in this queue. Find candidates in matching source passages.';
  }catch(error){if(generation===reviewState.generation)$('review-status').textContent=error.message;}
}
async function extractCandidates(){
  const documentId=$('document').value;const generation=state.generation;const provider=$('extraction-provider').value;const query=$('extraction-query').value.trim();if(!query){$('review-status').textContent='Enter a passage phrase to limit extraction.';return;}
  reviewState.busy=true;$('extract-candidates').disabled=true;$('extraction-provider').disabled=true;$('review-status').textContent='Finding source passages and extracting proposals…';
  try{const passages=await api(`/v1/documents/${documentId}/passages?query=${encodeURIComponent(query)}&limit=${provider==='openai'?1:5}`);if(!passages.passages.length)throw new Error('No matching passages. Try another phrase.');const result=await api('/v1/extraction/runs',{passage_ids:passages.passages.map(p=>p.id),provider,retry_failed:$('retry-extraction').checked});if(generation!==state.generation||documentId!==$('document').value)return;await loadCandidates();const count=result.runs.reduce((n,r)=>n+r.candidate_ids.length,0);const invalid=result.runs.reduce((n,r)=>n+r.validation_errors.length,0);$('review-status').textContent=`${count} proposals found or retrieved from cache. ${invalid?invalid+' invalid proposals excluded. ':''}Review is required before graph inclusion.`;
  }catch(error){if(generation===state.generation&&documentId===$('document').value)$('review-status').textContent=error.message;}
  finally{reviewState.busy=false;$('extract-candidates').disabled=$('document').disabled;$('extraction-provider').disabled=false;}
}
async function openCandidate(candidate){
  const generation=++state.evidenceGeneration;state.activeClaim=null;const body=drawerBase('Candidate review');body.append(element('span','badge neutral',candidate.state==='duplicate'?'Already recorded':candidate.state),element('h3',null,candidate.counterparty_name),element('p',null,label(candidate.predicate)),element('div','label-small','Exact source quote'),element('blockquote','source-quote',candidate.quote),element('p','muted',candidate.rationale));
  try{const passage=await api('/v1/passages/'+candidate.passage_id);if(generation!==state.evidenceGeneration)return;const issuer=state.entities.get(passage.document.issuer_id)?.canonical_name||'Filing issuer';body.append(element('p','candidate-direction',candidate.subject_is_issuer?`${issuer} → ${candidate.counterparty_name}`:`${candidate.counterparty_name} → ${issuer}`));sourceDetails(body,passage.document);const chars=Array.from(passage.text);const quoteChars=Array.from(candidate.quote);const start=Array.from(passage.text.slice(0,passage.text.indexOf(candidate.quote))).length+passage.start_offset;contextParagraph(body,passage,{quote:candidate.quote,start_offset:start,end_offset:start+quoteChars.length});
    if(candidate.state==='pending'){
      const form=element('form','review-form');const nameLabel=element('label','field-label','Canonical company name');nameLabel.htmlFor='canonical-company';const name=element('input');name.id='canonical-company';name.value=candidate.counterparty_name;name.maxLength=200;name.required=true;
      const entityLabel=element('label','field-label','Resolve company identity');entityLabel.htmlFor='resolved-company';const select=element('select');select.id='resolved-company';const create=element('option',null,'Use confirmed name · create if needed');create.value='';select.append(create);for(const entity of reviewState.entities){const option=element('option',null,entity.canonical_name);option.value=entity.id;select.append(option);if(entity.canonical_name.toLowerCase()===candidate.counterparty_name.toLowerCase())select.value=entity.id;}select.addEventListener('change',()=>{name.disabled=!!select.value;name.required=!select.value;});name.disabled=!!select.value;name.required=!select.value;
      const reviewerLabel=element('label','field-label','Reviewer identity');reviewerLabel.htmlFor='reviewer-name';const reviewer=element('input');reviewer.id='reviewer-name';reviewer.required=true;reviewer.maxLength=120;reviewer.placeholder='Your name or analyst ID';reviewer.value=sessionStorage.getItem('fig-reviewer')||'';
      const notesLabel=element('label','field-label','Review notes (optional)');notesLabel.htmlFor='review-notes';const notes=element('textarea');notes.id='review-notes';notes.maxLength=2000;
      const status=element('p','search-status');status.setAttribute('role','status');const actions=element('div','review-actions');const accept=element('button','button primary','Accept relationship');accept.type='submit';const reject=element('button','button secondary','Reject candidate');reject.type='button';actions.append(accept,reject);
      form.append(element('div','caveat','Acceptance confirms the company identity, positive relationship, direction, and support in this quote. Effective dates remain unknown.'),entityLabel,select,nameLabel,name,reviewerLabel,reviewer,notesLabel,notes,actions,status);body.append(form);
      async function decide(action){if(!reviewer.value.trim()){status.textContent='Enter a reviewer identity.';reviewer.focus();return;}accept.disabled=reject.disabled=true;status.textContent='Saving review…';try{const payload={action,expected_version:candidate.version,reviewer:reviewer.value.trim(),notes:notes.value};if(action==='accept'){if(select.value)payload.entity_id=select.value;else payload.canonical_name=name.value.trim();}await api('/v1/candidates/'+candidate.id+'/decisions',payload);sessionStorage.setItem('fig-reviewer',reviewer.value.trim());if(generation!==state.evidenceGeneration)return;await loadCompanies();$('review-status').textContent=action==='accept'?'Relationship accepted and graph refreshed.':'Candidate rejected. The graph is unchanged.';}catch(error){if(generation===state.evidenceGeneration){status.textContent=error.message;accept.disabled=reject.disabled=false;}}}
      form.addEventListener('submit',event=>{event.preventDefault();decide('accept');});reject.addEventListener('click',()=>decide('reject'));
    }else{const history=await api('/v1/candidates/'+candidate.id+'/decisions');if(generation!==state.evidenceGeneration)return;for(const decision of history.decisions){body.append(element('p','muted',`${decision.action==='accept'?'Accepted':'Rejected'} by ${decision.reviewer} · ${sourceDate(decision.decided_at)}`));if(decision.notes)body.append(element('p',null,decision.notes));}if(candidate.state==='duplicate')body.append(element('p','muted','An accepted claim with this quote, relationship, direction, and company identity already exists.'));}
    if(window.innerWidth<=900)$('evidence-title').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(error){if(generation===state.evidenceGeneration)body.append(element('p','caveat',error.message));}
}
$('extract-candidates').addEventListener('click',extractCandidates);$('candidate-state').addEventListener('change',()=>loadCandidates());$('more-candidates').addEventListener('click',()=>loadCandidates(true));
async function initializeWorkspace(){
  $('retry-connection').hidden=true;$('retry-connection').disabled=true;
  $('refresh').disabled=true;$('include-demo').disabled=true;$('ask-button').disabled=true;
  $('connection-status').textContent='Connecting to local workspace…';
  $('connection-detail').textContent='Checking database migrations and optional extraction configuration.';
  const [health,configuration]=await Promise.allSettled([api('/v1/health'),api('/v1/extraction/configuration')]);
  const option=$('extraction-provider').querySelector('[value="openai"]');
  reviewState.configured=configuration.status==='fulfilled'&&configuration.value.openai_configured;
  option.disabled=!reviewState.configured;
  if(!reviewState.configured)$('extraction-provider').value='rules';
  $('extraction-help').textContent=configuration.status==='rejected'
    ?'Model configuration could not be checked. Rules are available without an API key. Retry connection to check again.'
    :reviewState.configured?'Rules read up to five matching passages. OpenAI reads one and may incur provider charges.'
    :'Rules read up to five matching passages. Optional OpenAI extraction needs OPENAI_API_KEY and FIG_LLM_MODEL in server configuration, then an API restart.';
  if(health.status==='rejected'){
    $('connection-status').textContent='Workspace needs attention';
    $('connection-detail').textContent=health.reason.message+' Run fig migrate using the server configuration, then retry.';
    $('retry-connection').hidden=false;$('retry-connection').disabled=false;
    $('getting-started').open=true;return;
  }
  $('connection-status').textContent='Local workspace ready';
  const mode=health.value.storage_mode==='sqlite_development'?'SQLite local adapter':'PostgreSQL';
  $('connection-detail').textContent=`${mode} · migrations ${health.value.migration} · ${reviewState.configured?'optional model configured':'no model required for demo or rules'}.`;
  if(configuration.status==='rejected'){$('retry-connection').hidden=false;$('retry-connection').disabled=false;}
  await loadCompanies(true);
}
$('retry-connection').addEventListener('click',initializeWorkspace);
$('ask-form').addEventListener('submit',askResearch);
$('company').addEventListener('change',()=>selectCompany($('company').value));
$('include-demo').addEventListener('change',()=>loadCompanies());
$('refresh').addEventListener('click',()=>loadCompanies(true));
$('find-paths').addEventListener('click',findPaths);
$('path-target').addEventListener('change',()=>{$('path-results').replaceChildren();$('path-status').textContent='Select Find paths to query accepted claims.';});
$('compare-filings').addEventListener('click',compareFilings);
$('document').addEventListener('change',()=>{resetSearch();updateComparisonDocuments();loadDocumentMetadata();loadCandidates();});
$('search-form').addEventListener('submit',event=>{event.preventDefault();runSearch();});
$('load-more').addEventListener('click',()=>runSearch(true));
$('close-evidence').addEventListener('click',resetEvidence);
document.querySelectorAll('[data-query]').forEach(button=>button.addEventListener('click',()=>{$('query').value=button.dataset.query;runSearch();}));
let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(renderGraph,150);});
try{if(sessionStorage.getItem('fig-guide-collapsed')==='true')$('getting-started').open=false;}catch{}
$('getting-started').addEventListener('toggle',()=>{try{sessionStorage.setItem('fig-guide-collapsed',String(!$('getting-started').open));}catch{}});
initializeWorkspace();
