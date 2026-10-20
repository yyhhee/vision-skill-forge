import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {chromium} from '@playwright/test';
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
for(const id of ['09','10','11']){
 const dir=`qa/run-flow/iteration-04/${id}`;
 const env=JSON.parse(await fs.readFile(`${dir}/environment.json`,'utf8'));
 const png=await fs.readFile(`${dir}/implementation.png`);
 assert.equal(png.readUInt32BE(16),env.width);assert.equal(png.readUInt32BE(20),env.height);assert.equal(env.dpr,1);assert.equal(env.fonts,'loaded');assert.equal(env.language,'zh-CN');assert.equal(env.timezone,'Asia/Shanghai');assert.equal(env.reducedMotion,true);assert.deepEqual(env.errors,[]);assert.deepEqual(env.network,[]);assert.equal(env.sha256,hash(png));assert.deepEqual(env.storage,{workspace:null,runs:null});
 const pair=JSON.parse(await fs.readFile(`${dir}/comparison/metrics.json`,'utf8'));assert.equal(pair.resized,false);assert.equal(pair.masked,false);assert.equal(pair.actualSha256,env.sha256);assert.equal(hash(await fs.readFile(pair.reference)),pair.referenceSha256);
}
const approval=JSON.parse(await fs.readFile('qa/04/approved-baseline.json','utf8'));assert.equal(hash(await fs.readFile(path.join('qa/04',approval.baseline.path))),approval.baseline.sha256);assert.equal(hash(await fs.readFile(path.join('qa/04',approval.immutableOriginal.path))),approval.immutableOriginal.sha256);
const browser=await chromium.launch({headless:true,...(process.env.VSF_CHROMIUM_EXECUTABLE?{executablePath:process.env.VSF_CHROMIUM_EXECUTABLE}:{})});const errors=[],badRequests=[];
try{const context=await browser.newContext({viewport:{width:1513,height:1040},deviceScaleFactor:1});await context.route('**/*',r=>new URL(r.request().url()).origin==='http://127.0.0.1:6174'?r.continue():r.abort());const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400)badRequests.push({url:r.url(),status:r.status()});});await page.goto('http://127.0.0.1:6174/qa/run-flow/index.html');await page.getByLabel('选择页面').selectOption('11');await page.getByRole('button',{name:'50%叠加',exact:true}).click();await page.waitForFunction(()=>document.getElementById('picture').complete&&document.getElementById('picture').naturalWidth===1513);assert.match(await page.locator('#picture').getAttribute('src'),/iteration-04\/11\/comparison\/overlay-50.png/);await page.getByRole('button',{name:'局部：evidence',exact:true}).click();await page.waitForFunction(()=>document.getElementById('picture').complete&&document.getElementById('picture').naturalWidth===1196);assert.deepEqual(errors,[]);assert.deepEqual(badRequests,[]);await context.close();}finally{await browser.close();}
console.log(JSON.stringify({evidence:'3 native captures, no external network or normal-storage writes, immutable originals and approved04 hashes verified',viewer:'page selection, overlay and focused evidence passed',errors,badRequests},null,2));
