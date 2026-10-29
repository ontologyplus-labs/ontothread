/** Offline acceptance against a fresh `ontothread demo` installation. No model is called. */
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {chromium} from 'playwright';

const base=process.env.FIG_BASE_URL||'http://127.0.0.1:8000';
const browser=await chromium.launch({headless:true});
const errors=[];
const external=[];
await mkdir('test-results',{recursive:true});
async function context(){
  const ctx=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  await ctx.route('**/*',route=>{
    if(new URL(route.request().url()).origin!==new URL(base).origin){external.push(route.request().url());return route.abort();}
    return route.continue();
  });
  ctx.on('page',page=>page.on('pageerror',error=>errors.push(error.message)));
  return ctx;
}
async function ready(page){await page.locator('#connection-status').filter({hasText:'Local workspace ready'}).waitFor();await page.locator('#company:not([disabled])').waitFor();}
async function text(page,id,value){await page.locator(id).filter({hasText:value}).waitFor();}
let page;
try{
  // Give the locally started service up to 30 seconds to bind.
  for(let i=0;i<60;i++){
    try{if((await fetch(base+'/v1/health')).ok)break;}catch{}
    if(i===59)throw new Error('Local API did not become ready');
    await new Promise(resolve=>setTimeout(resolve,500));
  }
  const ctx=await context();page=await ctx.newPage();await page.goto(base);await ready(page);
  assert.equal(await page.locator('#include-demo').isChecked(),false);
  await text(page,'#sec-demo-notice','Real SEC excerpt snapshot');
  assert.equal(await page.locator('#demo-notice').isVisible(),false);
  assert.match(await page.locator('#company option:checked').textContent(),/NVIDIA CORP/);
  assert.equal(await page.locator('#company option').count(),5);
  await text(page,'#data-mode','SEC EXCERPT SNAPSHOT');
  assert.equal(await page.locator('#extraction-provider option[value="openai"]').isDisabled(),true);
  await page.locator('#getting-started summary').click();
  await page.locator('#ask-button').click();await text(page,'#ask-status','2 source citations');
  await text(page,'#ask-results','Broadcom');
  const target=await page.locator('#path-target option').filter({hasText:'Samsung'}).getAttribute('value');
  await page.locator('#path-target').selectOption(target);await page.locator('#path-hops').selectOption('3');
  await page.locator('#find-paths').click();await text(page,'#path-results','3 HOPS');
  await page.locator('.path-results .path-edge').first().click();await text(page,'#evidence-content','Exact source quote');await page.locator('#evidence-content mark').waitFor();
  await text(page,'#evidence-content','Selected excerpt only');
  assert.match(await page.getByRole('link',{name:'Open source filing ↗'}).getAttribute('href'),/^https:\/\/www\.sec\.gov\/Archives\//);
  await page.locator('#query').fill('manufacturing');await page.locator('#search-button').click();await text(page,'#search-status','1 passage');
  await page.locator('#search-results button').first().click();await text(page,'#evidence-title','Source passage');
  await page.locator('#query').fill('missing-phrase-zzzzz');await page.locator('#search-button').click();await text(page,'#search-status','No passages match');
  await page.getByRole('link',{name:'Review candidates',exact:true}).click();
  await page.locator('#extract-candidates').click();await text(page,'#review-status','2 proposals');
  for(const [name,action,message] of [['Taiwan Semiconductor Manufacturing Company Limited','Accept relationship','Relationship accepted'],['Samsung Electronics Co., Ltd.','Reject candidate','Candidate rejected']]){
    await page.locator('.candidate-card').filter({hasText:name}).click();
    await page.locator('#reviewer-name').fill('demo-browser-check');
    await page.locator('#review-notes').fill('Disposable demo workflow exercise, not a new independent source assessment.');
    if(action==='Accept relationship'){
      await page.locator('#resolved-company').selectOption({label:'TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD'});
    }
    await page.getByRole('button',{name:action,exact:true}).click();await text(page,'#review-status',message);
  }
  await page.locator('.candidate-card').filter({hasText:'Taiwan Semiconductor Manufacturing Company Limited'}).click();await text(page,'#evidence-content','Accepted by demo-browser-check');
  await page.reload();await ready(page);await text(page,'#candidate-list','accepted');await text(page,'#candidate-list','rejected');
  // Section links and graph evidence must work from the keyboard.
  await page.getByRole('link',{name:'Relationships',exact:true}).focus();await page.keyboard.press('Enter');
  assert.equal(new URL(page.url()).hash,'#relationships');
  await page.locator('.edge-button').first().focus();await page.keyboard.press('Enter');await text(page,'#evidence-title','Relationship evidence');
  assert.equal(await page.locator('.edge-button').first().evaluate(el=>el===document.activeElement),true);
  await page.screenshot({path:'test-results/workspace-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'Mobile page overflows horizontally');
  await page.screenshot({path:'test-results/workspace-mobile.png',fullPage:true});await ctx.close();

  const failure=await context();page=await failure.newPage();
  await page.route('**/v1/health',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:{message:'Database unavailable or migrations missing'}})}));
  await page.goto(base);await text(page,'#connection-status','needs attention');
  assert.equal(await page.locator('#ask-button').isDisabled(),true);
  await page.unroute('**/v1/health');await page.locator('#retry-connection').click();await ready(page);
  // A failed graph request must show a recoverable message, not stale relationships.
  await page.route('**/v1/graph/neighbors',route=>route.abort());
  await page.locator('#refresh').click();await text(page,'#global-error','Cannot reach');await text(page,'#graph','could not be loaded');
  await page.unroute('**/v1/graph/neighbors');await page.locator('#refresh').click();await page.locator('.edge-button').first().waitFor();await failure.close();

  const empty=await context();page=await empty.newPage();
  await page.route('**/v1/entities?*',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({entities:[],truncated:false,next_offset:null})}));
  await page.goto(base);await text(page,'#corpus-notice','Run ontothread demo');
  assert.equal(await page.locator('#getting-started').getAttribute('open'),'');
  assert.equal(await page.locator('#ask-button').isDisabled(),true);assert.equal(await page.locator('#find-paths').isDisabled(),true);await empty.close();

  const configuration=await context();page=await configuration.newPage();
  await page.route('**/v1/extraction/configuration',route=>route.fulfill({status:503,contentType:'application/json',body:'{}'}));
  await page.goto(base);await ready(page);await text(page,'#extraction-help','could not be checked');
  assert.equal(await page.locator('#extraction-provider option[value="openai"]').isDisabled(),true);await configuration.close();
  assert.deepEqual(errors,[],'Browser JavaScript errors');assert.deepEqual(external,[],'Offline demo attempted external requests');
  console.log('Browser acceptance passed: questions, 3-hop paths, quotes, search, review persistence, keyboard, 390px layout, and recovery. No external requests.');
}catch(error){if(page&&!page.isClosed())await page.screenshot({path:'test-results/failure.png',fullPage:true}).catch(()=>{});throw error;}
finally{await browser.close();}
