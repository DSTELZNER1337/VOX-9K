const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');

function app() {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: id === 'engineSelect' ? 'kokoro' : id === 'voiceSelect' ? 'af_sarah' : id === 'computeSelect' ? 'auto' : '1',
      textContent: '', innerHTML: '', style: {}, hidden: false, scrollTop: 0, offsetTop: 0, clientHeight: 400, disabled: false, selectedIndex: 0,
      options: [{text: 'Kokoro'}], selectedOptions: [], listeners: {}, children: [],
      appendChild(x) {this.children.push(x)},
      get firstChild() {return this.children[0]},
      querySelector() {return {disabled: false}},
      addEventListener(event, handler) {this.listeners[event] = handler},
    });
    return elements.get(id);
  }
  const context = vm.createContext({
    console, Uint8Array, Float32Array, DataView, TextDecoder, Intl, AbortController, DOMException,
    performance, setTimeout, clearTimeout, getComputedStyle: () => ({height: "400px"}),
    URL: {createObjectURL: () => 'blob:test', revokeObjectURL() {}},
    window: {crypto: require('node:crypto').webcrypto, addEventListener() {}},
    document: {getElementById: element, createElement: () => element(Symbol())},
    fetch: async () => ({ok: true, json: async () => ({engines: {kokoro: {modes: {auto:true,cpu:true,cuda:false}}}})}),
  });
  context.crypto = context.window.crypto;
  const helper = path.join(root, 'vox_helpers.js');
  if (fs.existsSync(helper)) vm.runInContext(fs.readFileSync(helper, 'utf8'), context);
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  const script = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');
  vm.runInContext(script, context);
  return {context, element, run: code => vm.runInContext(code, context)};
}

test('Markdown cleanup preserves decimal content', () => {
  assert.equal(app().run('cleanText("# Title\\n**8.2** `units`\\n- item")'), 'Title\n8.2 units\nitem');
});
test('chunk order, punctuation and decimals', () => {
  const a = app();
  assert.equal(a.run('splitIntoChunks("Value 8.2 is correct. Really? Yes!").join(" ")'), 'Value 8.2 is correct. Really? Yes!');
});
test('empty chunks', () => assert.equal(app().run('splitIntoChunks("").length'), 0));
test('unpunctuated text respects backend limit', () => {
  const a = app();
  assert.equal(a.run('splitIntoChunks("x".repeat(7000)).every(c => c.length <= 3000)'), true);
  assert.equal(a.run('splitIntoChunks("x".repeat(7000)).join("").length'), 7000);
});
test('short time stretch is passthrough', () => assert.equal(app().run('stretchQwenPcmPreservePitch(new Float32Array(100), 2).length'), 100));
test('time stretch stays finite and bounded for a sine', () => {
  const a = app();
  for (const speed of [.5, 1, 1.5, 2]) {
    assert.equal(a.run(`{const input = Float32Array.from({length:24000}, (_,i)=>.5*Math.sin(2*Math.PI*220*i/24000)); const output=stretchQwenPcmPreservePitch(input, ${speed}); output.every(Number.isFinite) && output.every(x=>Math.abs(x)<=.501) && Math.abs(output.length-24000/${speed})<=1024}`), true);
  }
});
test('volume, speed and pitch flag', () => {
  const a = app();
  a.run('currentAudio = {preservesPitch:false}; speedSlider.value="1.5"; volumeSlider.value="0.3"; applyAudioSettings()');
  assert.equal(a.run('currentAudio.playbackRate'), 1.5);
  assert.equal(a.run('currentAudio.volume'), .3);
  assert.equal(a.run('currentAudio.preservesPitch'), true);
});
test('stop clears playback and aborts fetches', () => {
  const a = app();
  a.run('isActive=true; const ctrl=new AbortController(); fetchControllers.set(0,ctrl);');
  a.element('stopButton').listeners.click();
  assert.equal(a.run('!isActive && !isPaused && speechChunks.length===0 && fetchControllers.size===0 && ctrl.signal.aborted'), true);
});
test('engine selection populates Qwen voices', () => {
  const a = app();
  a.element('engineSelect').value = 'qwen';
  a.run('populateVoiceOptions()');
  assert.equal(a.element('voiceSelect').value, 'Ryan');
});
test('cancel is scoped to the active request', async () => {
  const a = app();
  let body;
  a.context.fetch = async (url, opts) => {body = JSON.parse(opts.body); return {ok: true}};
  a.run('activeQwenRequestId="owner:1"; cancelQwenServerGeneration()');
  assert.equal(body.request_id, 'owner:1');
});
test('old Qwen failure cannot stop the new session', async () => {
  const a = app();
  a.run('playbackSession=2; isActive=true; waitForQwenReady=async()=>{throw new Error("stale")};');
  await a.run('playQwenSession(1)');
  assert.equal(a.run('isActive'), true);
});
test('old controller cleanup cannot remove a newer Qwen controller', async () => {
  const a = app();
  let reject;
  a.context.fetch = () => new Promise((_, r) => {reject=r});
  a.run('speechChunks=["hi"]; playbackSession=1;');
  const old = a.run('streamQwenTextChunk(0,1)').catch(()=>{});
  a.run('const newerController = new AbortController(); fetchControllers.set("qwen-0",newerController)');
  reject(new Error('old failure')); await old;
  assert.equal(a.run('fetchControllers.get("qwen-0")===newerController'), true);
});
test('Kokoro pause and resume keep the current audio', async () => {
  const a=app();
  a.run('isActive=true; currentAudio={paused:false,preservesPitch:true,pause(){this.paused=true},async play(){this.paused=false}}');
  await a.element('pauseButton').listeners.click();
  assert.equal(a.run('isPaused && currentAudio.paused'),true);
  await a.element('pauseButton').listeners.click();
  assert.equal(a.run('!isPaused && !currentAudio.paused'),true);
});
test('Qwen pause and resume suspend the context', async () => {
  const a=app();
  a.run('isActive=true; activeEngine="qwen"; qwenAudioContext={state:"running",async suspend(){this.state="suspended"},async resume(){this.state="running"}}');
  await a.element('pauseButton').listeners.click();
  assert.equal(a.run('isPaused && qwenAudioContext.state==="suspended"'),true);
  await a.element('pauseButton').listeners.click();
  assert.equal(a.run('!isPaused && qwenAudioContext.state==="running"'),true);
});
test('late pause completion cannot change a new session status', async () => {
  const a=app();let complete;
  a.context.suspendLater=()=>new Promise(r=>{complete=r});
  a.run('isActive=true;activeEngine="qwen";qwenAudioContext={suspend:suspendLater};playbackSession=1');
  const pausing=a.element('pauseButton').listeners.click();
  a.run('playbackSession=2;statusDisplay.textContent="New read"');
  complete();await pausing;
  assert.equal(a.element('status').textContent,'New read');
});
test('new Read with empty text resets playback state', () => {
  const a=app();a.element('promptText').value='';a.run('isActive=true;isPaused=true');
  a.element('readButton').listeners.click();
  assert.equal(a.run('!isActive && !isPaused'),true);
  assert.equal(a.element('status').textContent,'Nothing to read');
});
test('old Kokoro cleanup preserves the new cache and controller', async () => {
  const a=app();let reject;
  a.context.fetch=()=>new Promise((_,r)=>{reject=r});
  a.run('speechChunks=["hello"];playbackSession=1');
  const old=a.run('fetchChunkAudio(0,1)').catch(()=>{});
  a.run('const newer=new AbortController();fetchControllers.set(0,newer);const newerPromise=Promise.resolve("new");chunkAudioCache.set(0,newerPromise)');
  reject(new Error('old'));await old;
  assert.equal(a.run('fetchControllers.get(0)===newer && chunkAudioCache.get(0)===newerPromise'),true);
});
test('malformed stream cancels and releases its reader', async () => {
  const a=app();let cancelled=false,released=false;
  const reader={async read(){return {done:true}},async cancel(){cancelled=true},releaseLock(){released=true}};
  a.context.fetch=async()=>({ok:true,body:{getReader:()=>reader}});
  a.run('speechChunks=["hi"];playbackSession=1');
  await assert.rejects(a.run('streamQwenTextChunk(0,1)'),/ended unexpectedly/);
  assert.equal(cancelled && released,true);
});
test('Qwen startup failure is immediate and redacted', async () => {
  const a=app();a.context.fetch=async()=>({ok:true,json:async()=>({status:'error',error:'PRIVATE/PATH'})});
  await assert.rejects(a.run('waitForQwenReady(0)'),/Check the local sidecar console/);
});
test('late health response cannot change the next session', async () => {
  const a=app();let resolve;
  a.context.fetch=()=>new Promise(r=>{resolve=r});
  const waiting=a.run('waitForQwenReady(0)');
  a.run('playbackSession=1;statusDisplay.textContent="New read"');
  resolve({ok:true,json:async()=>({status:'loading'})});
  await assert.rejects(waiting,{name:'AbortError'});
  assert.equal(a.element('status').textContent,'New read');
});
test('Stop aborts the readiness request', async () => {
  const a=app();
  a.context.fetch=(url,options)=>new Promise((r,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('cancelled','AbortError'))));
  const waiting=a.run('waitForQwenReady(0)');
  a.element('stopButton').listeners.click();
  await assert.rejects(waiting,{name:'AbortError'});
  assert.equal(a.run('fetchControllers.size'),0);
});

function frame(values=[], rate=24000, index=0, flags=0) {
  const bytes = new Uint8Array(16+4*values.length);
  const view = new DataView(bytes.buffer);
  [values.length*4, rate, index, flags].forEach((x,i)=>view.setUint32(i*4,x,true));
  values.forEach((x,i)=>view.setFloat32(16+i*4,x,true));
  return bytes;
}
function parser() {
  const a=app();
  assert.equal(a.run('typeof VoxPcmParser'), 'function');
  return a.run('new VoxPcmParser()');
}
test('PCM parser accepts partial frames and multiple frames', () => {
  const p=parser(), data=frame([.25,-.25]);
  assert.equal(p.push(data.slice(0,9)).length,0);
  const rest=new Uint8Array(data.length-9+16); rest.set(data.slice(9));rest.set(frame([],24000,1,1),data.length-9);
  const frames=p.push(rest);
  assert.deepEqual(Array.from(frames[0].samples),[.25,-.25]);
  assert.equal(p.ended,true); p.finish();
});
test('PCM parser rejects truncated stream', () => {
  const p=parser();p.push(frame([.1]).slice(0,18));assert.throws(()=>p.finish());
});
test('PCM parser requires end marker', () => {
  const p=parser();p.push(frame([.1]));assert.throws(()=>p.finish());
});
test('PCM parser rejects bad rate, flags, index, NaN and excessive size', () => {
  for (const data of [frame([.1],0),frame([.1],24000,0,3),frame([.1],24000,4),frame([NaN])]) {
    assert.throws(()=>parser().push(data));
  }
  const data=frame();new DataView(data.buffer).setUint32(0,0x7fffffff,true);
  assert.throws(()=>parser().push(data));
});
test('PCM parser reports error frames', () => {
  const data=frame([0],24000,0,2);data.set(new TextEncoder().encode('oops'),16);
  assert.throws(()=>parser().push(data), /oops/);
});

test('header and subtle footer attribution render', () => {
  const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
  assert.match(html,/<title>VOX-9K<\/title>/);assert.match(html,/<h1>VOX-9K<\/h1>/);
  assert.match(html,/<footer class="brand-footer">Created by: StelzTools<\/footer>/);
  assert.doesNotMatch(html,/by DST/);
});
test('cleanup matches the original rules', () => {
  const original=text=>text.replace(/^={3,}\s*$/gm,"").replace(/^-{3,}\s*$/gm,"").replace(/^_{3,}\s*$/gm,"").replace(/^\*{3,}\s*$/gm,"").replace(/^~{3,}\s*$/gm,"").replace(/^#{1,6}\s+/gm,"").replace(/\*\*/g,"").replace(/__/g,"").replace(/\x60/g,"").replace(/^>\s?/gm,"").replace(/^\s*[-*+]\s+/gm,"").replace(/\n{3,}/g,"\n\n").trim();
  const a=app();
  for (const raw of ['# Title\n**Hello** \x60code\x60.\n- item','===\n\nHello.\n\n\nNext.','> Quote\n____\nText','\r\n# Heading\r\n8.2 and 3.14.','\u{1f600} **Hello** __world__.','<script>literal</script>','**\n+ One\n  - Two','']) {
    assert.equal(a.run('cleanText('+JSON.stringify(raw)+')'),original(raw));
  }
});
test('source mapping preserves original Markdown, whitespace, emoji and HTML', () => {
  const a=app(),raw='# Title\n**Hello \u{1f600}.**\n> Next <tag>.\n---\n';
  a.context.rawForTest=raw;
  const ends=Array.from(a.run('readChunkEnds(rawForTest, ["Title Hello \\u{1f600}.", "Next <tag>."])'));
  assert.equal(raw.slice(0,ends[0]),'# Title\n**Hello \u{1f600}.');
  assert.equal(raw.slice(ends[0],ends[1]),'**\n> Next <tag>.');
  assert.equal(a.run('readChunkEnds("wrong",["unmatched"]).length'),0);
});
test('read view retains full text and original height before audio starts', () => {
  const a=app();a.run('isActive=true;promptText.value="# First. Second.";beginReadingView(promptText.value,["First.","Second."],0)');
  assert.equal(a.element('readRemaining').textContent,'# First. Second.');
  assert.equal(a.element('readCurrent').textContent,'');
  assert.equal(a.element('promptText').hidden,true);assert.equal(a.element('readView').hidden,false);
  assert.equal(a.element('readView').style.height,'400px');
});
test('current and completed chunks brighten monotonically', () => {
  const a=app();a.run('isActive=true;beginReadingView("First. Second.",["First.","Second."],0);markReadingChunk(0,0)');
  assert.equal(a.element('readCurrent').textContent,'First.');assert.equal(a.element('readRemaining').textContent,' Second.');
  a.run('markReadingChunk(1,0);markReadingChunk(0,0)');
  assert.equal(a.element('readCompleted').textContent,'First.');assert.equal(a.element('readCurrent').textContent,' Second.');
});
test('pause freezes highlights and stale callbacks cannot change the next read', () => {
  const a=app();a.run('isActive=true;beginReadingView("One. Two.",["One.","Two."],0);markReadingChunk(0,0);isPaused=true;markReadingChunk(1,0)');
  assert.equal(a.element('readCurrent').textContent,'One.');
  a.run('isPaused=false;playbackSession=1;beginReadingView("New.",["New."],1);markReadingChunk(1,0);endReadingView(0)');
  assert.equal(a.element('readView').hidden,false);assert.equal(a.element('readRemaining').textContent,'New.');
});
test('Stop restores editable original input', () => {
  const a=app();a.run('promptText.value="**Original.**";isActive=true;beginReadingView(promptText.value,["Original."],0);markReadingChunk(0,0)');
  a.element('stopButton').listeners.click();
  assert.equal(a.element('readView').hidden,true);assert.equal(a.element('promptText').hidden,false);
  assert.equal(a.element('promptText').value,'**Original.**');assert.equal(a.run('readingViewState'),null);
});
test('both completion paths return to editing', async () => {
  for(const engine of ['kokoro','qwen']) {
    const a=app();a.run('isActive=true;beginReadingView("Done.",["Done."],0)');
    if(engine==='kokoro') await a.run('speechChunks=[];currentChunk=0;playCurrentChunk(0)');
    else a.run('qwenGenerationComplete=true;finishQwenIfDone(0)');
    assert.equal(a.element('readView').hidden,true);assert.equal(a.element('promptText').hidden,false);
    assert.equal(a.element('status').textContent,'Finished');
  }
});
test('Qwen highlights only when queued PCM actually starts playing', () => {
  const a=app();a.run('isActive=true;isPaused=true;beginReadingView("First. Next.",["First.","Next."],0);enqueueQwenPcm(new Float32Array(100),24000,0,0)');
  assert.equal(a.element('readCurrent').textContent,'');
  a.run('qwenAudioContext={state:"running",currentTime:0,createBuffer(){return {copyToChannel(){}}},createBufferSource(){return {playbackRate:{value:1},connect(){},start(){this.started=true}}}};qwenGainNode={gain:{value:1}};isPaused=false;playNextQwenBuffer(0)');
  assert.equal(a.element('readCurrent').textContent,'First.');assert.equal(a.run('qwenCurrentSource.started'),true);
});
test('Qwen errors restore editing without modifying input', async () => {
  const a=app();a.run('isActive=true;promptText.value="Keep me.";beginReadingView(promptText.value,["Keep me."],0);waitForQwenReady=async()=>{throw new Error("synthetic failure")}');
  await a.run('playQwenSession(0)');
  assert.equal(a.element('readView').hidden,true);assert.equal(a.element('promptText').value,'Keep me.');
});


// Exercise the production DSP with no models or browser.
for (const kind of ['sine', 'speech-like', 'silence', 'amplitude-step']) {
  test('WSOLA preserves seams, range and duration: '+kind, () => {
    const a=app();a.context.kind=kind;
    a.run(`fixture=Float32Array.from({length:15360*4},(_,i)=>{
      const t=i/24000;
      if(kind==='silence') return 0;
      if(kind==='amplitude-step') return i<17000?.7:-.6;
      if(kind==='sine') return .5*Math.sin(2*Math.PI*223*t);
      return .3*(.6+.4*Math.sin(2*Math.PI*3*t))*(Math.sin(2*Math.PI*173*t)+.4*Math.sin(2*Math.PI*346*t)+.2*Math.sin(2*Math.PI*1013*t));
    })`);
    for(const speed of [.5,.7,1,1.2,1.37,1.5,1.8,2]) {
      a.context.speed=speed;
      const frames=a.run(`Array.from({length:4},(_,i)=>{
        const input=fixture.slice(i*15360,(i+1)*15360);
        return {input,output:stretchQwenPcmPreservePitch(input,speed)};
      })`);
      for(let i=0;i<frames.length;i++) {
        const {input,output}=frames[i];
        assert.equal(output.length,Math.round(input.length/speed));
        assert.equal(output[0],input[0],'preserve true head');
        assert.equal(output.at(-1),input.at(-1),'preserve true tail');
        assert.ok(output.every(Number.isFinite));
        assert.ok(output.every(x=>Math.abs(x)<=.701));
        if(i) assert.equal(output[0]-frames[i-1].output.at(-1),input[0]-frames[i-1].input.at(-1),'no added seam discontinuity');
        if(kind==='sine') {
          let maxDelta=0;
          for(let j=1;j<output.length;j++) maxDelta=Math.max(maxDelta,Math.abs(output[j]-output[j-1]));
          assert.ok(maxDelta<.035,'smooth internal overlaps');
        }
      }
    }
  });
}
test('WSOLA preserves tone pitch at 1.5x', () => {
  const output=app().run('stretchQwenPcmPreservePitch(Float32Array.from({length:48000},(_,i)=>.5*Math.sin(2*Math.PI*223*i/24000)),1.5)');
  let bestLag=0,bestError=Infinity;
  for(let lag=90;lag<=125;lag++) {
    let error=0;
    for(let i=2048;i<output.length-2048-lag;i++) error+=(output[i]-output[i+lag])**2;
    if(error<bestError){bestError=error;bestLag=lag}
  }
  assert.ok(Math.abs(24000/bestLag-223)<4);
});
test('short buffers pass through; threshold buffers retain endpoints', () => {
  const a=app();
  for(const n of [0,1,127,2047,2048,2049,3073]) for(const speed of [.5,1.2,1.5,1.8,2]) {
    a.context.n=n;a.context.speed=speed;
    const {input,output}=a.run('{const input=Float32Array.from({length:n},(_,i)=>.4*Math.sin(i*.07));({input,output:stretchQwenPcmPreservePitch(input,speed)})}');
    assert.equal(output.length,n<2048?n:Math.round(n/speed));
    assert.ok(output.every(Number.isFinite));
    if(n){assert.equal(output[0],input[0]);assert.equal(output.at(-1),input.at(-1))}
  }
});
function scheduledApp() {
  const a=app();
  a.run(`
    sources=[];isActive=true;speechChunks=["First.","Next.","Last."];
    qwenAudioContext={
      state:"running",currentTime:10,
      createBuffer(channels,n,rate){return {duration:n/rate,copyToChannel(){}}},
      createBufferSource(){const source={
        playbackRate:{value:1},connect(){},
        start(at){this.when=at},stop(){this.stopped=true}
      };sources.push(source);return source},
      close(){this.state="closed";return Promise.resolve()},
      suspend(){this.state="suspended";return Promise.resolve()},
      resume(){this.state="running";return Promise.resolve()}
    };
    qwenGainNode={gain:{value:1}};
    beginReadingView("First. Next. Last.",speechChunks,0);
  `);
  return a;
}
test('audio-clock scheduling keeps one ahead without early highlighting', () => {
  const a=scheduledApp();
  a.run('for(let i=0;i<3;i++)enqueueQwenPcm(new Float32Array(2400),24000,i,0)');
  assert.equal(a.run('sources.length'),2);
  assert.equal(a.run('sources[1].when'),10.1);
  assert.equal(a.element('readCurrent').textContent,'First.');
  a.run('qwenAudioContext.currentTime=10.105;sources[0].onended()');
  assert.equal(a.run('sources.length'),3);
  assert.ok(Math.abs(a.run('sources[2].when')-10.2)<1e-9);
  assert.equal(a.element('readCurrent').textContent,' Next.');
  assert.equal(a.run('sources.every(s=>s.playbackRate.value===1)'),true);
});
test('scheduler plays each buffer once and finishes after the final source', () => {
  const a=scheduledApp();
  a.run('for(let i=0;i<5;i++)enqueueQwenPcm(new Float32Array(2400),24000,0,0);qwenGenerationComplete=true');
  for(let i=0;i<4;i++) {assert.equal(a.run('isActive'),true);a.run('sources['+i+'].onended()')}
  assert.equal(a.run('isActive'),true);
  a.run('sources[4].onended()');
  assert.equal(a.run('sources.length'),5);
  assert.equal(a.run('qwenScheduledSources.length'),0);
  assert.equal(a.run('isActive'),false);
  assert.equal(a.run('statusDisplay.textContent'),'Finished');
});
test('speed edits apply to unscheduled frames with playbackRate remaining one', () => {
  const a=scheduledApp();
  a.run('for(let i=0;i<4;i++)enqueueQwenPcm(new Float32Array(15360),24000,0,0);speedSlider.value="1.5";qwenAudioContext.currentTime=10.65;sources[0].onended()');
  assert.equal(a.run('sources[0].buffer.duration'),.64);
  assert.equal(a.run('sources[1].buffer.duration'),.64);
  assert.ok(Math.abs(a.run('sources[2].buffer.duration')-.64/1.5)<1e-9);
  assert.ok(Math.abs(a.run('sources[2].when')-11.28)<1e-9);
});
test('Stop cancels both scheduled sources and clears handlers and timeline', () => {
  const a=scheduledApp();
  a.run('for(let i=0;i<3;i++)enqueueQwenPcm(new Float32Array(2400),24000,0,0)');
  a.element('stopButton').listeners.click();
  assert.equal(a.run('sources.every(s=>s.stopped && s.onended===null)'),true);
  assert.equal(a.run('qwenScheduledSources.length===0 && qwenNextStartTime===0 && !qwenCurrentSource && qwenAudioQueue.length===0'),true);
});
test('pause holds scheduled audio and resume does not consume extra buffers', async () => {
  const a=scheduledApp();
  a.run('for(let i=0;i<3;i++)enqueueQwenPcm(new Float32Array(2400),24000,0,0);activeEngine="qwen"');
  await a.element('pauseButton').listeners.click();
  a.run('playNextQwenBuffer(0)');
  assert.equal(a.run('sources.length'),2);
  assert.equal(a.run('qwenAudioContext.state'),'suspended');
  await a.element('pauseButton').listeners.click();
  assert.equal(a.run('qwenAudioContext.state'),'running');
  assert.equal(a.run('sources.length'),2);
});
test('starvation restarts now; stale ended callbacks cannot alter the new session', () => {
  const a=scheduledApp();
  a.run('enqueueQwenPcm(new Float32Array(2400),24000,0,0);sources[0].onended();qwenAudioContext.currentTime=11;enqueueQwenPcm(new Float32Array(2400),24000,1,0)');
  assert.equal(a.run('sources[1].when'),11);
  a.run('const oldEnded=sources[1].onended;playbackSession++;oldEnded()');
  assert.equal(a.run('qwenScheduledSources.length'),1);
});

test('uneven streamed frames and a short final packet keep order and documented duration', () => {
  const a=app();
  for(const speed of [.7,1.2,1.5,1.8]) {
    a.context.speed=speed;
    const rows=a.run('{let offset=0;[15360,11777,1024].map(n=>{const input=Float32Array.from({length:n},(_,i)=>.4*Math.sin((i+offset)*.05));offset+=n;return {input,output:stretchQwenPcmPreservePitch(input,speed)}})}');
    const actual=rows.reduce((n,r)=>n+r.output.length,0);
    const expected=rows.reduce((n,r)=>n+Math.round(r.input.length/speed),0);
    assert.equal(actual-expected,1024-Math.round(1024/speed));
    for(let i=1;i<rows.length;i++) assert.equal(rows[i].output[0]-rows[i-1].output.at(-1),rows[i].input[0]-rows[i-1].input.at(-1));
  }
});
