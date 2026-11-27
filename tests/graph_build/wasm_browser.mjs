// A disposable Chromium profile and the built-in Node WebSocket API keep the
// browser control dependency-free. No application JavaScript implements the UI.
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [executable, url, revision] = process.argv.slice(2);
if (!executable || !url || !revision) throw new Error('usage: node wasm_browser.mjs CHROME URL REVISION');
const profile = await mkdtemp(join(tmpdir(), 'graph-wasm-chrome-'));
const child = spawn(executable, ['--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-extensions',
  '--disable-background-networking', '--disable-component-update',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
let diagnostics = '';
let spawnError;
child.on('error', error => { spawnError = error; });
child.stderr.on('data', data => { diagnostics = (diagnostics + data).slice(-16000); });
let socket;
let readState;
let sequence = 0;
const pending = new Map();
const requests = [];
const failures = [];
const exceptions = [];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const deadline = Date.now() + 60000;
async function until(check) {
  while (Date.now() < deadline) {
    const value = await check();
    if (value) return value;
    await delay(100);
  }
  throw new Error(`Browser deadline exceeded: ${diagnostics}`);
}
try {
  const port = await until(async () => {
    try { return Number((await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]); }
    catch { if (spawnError) throw spawnError; if (child.exitCode !== null || child.signalCode !== null) throw new Error(`Chrome exited ${child.exitCode}: ${diagnostics}`); }
  });
  const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const waiter = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) waiter?.reject(new Error(JSON.stringify(message.error)));
      else waiter?.resolve(message.result);
    }
    if (message.method === 'Network.responseReceived') requests.push({ url: message.params.response.url,
      status: message.params.response.status, mimeType: message.params.response.mimeType });
    if (message.method === 'Network.loadingFailed') failures.push(message.params);
    if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails);
  };
  function command(method, params = {}) {
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
      pending.set(id, { resolve: result => { clearTimeout(timeout); resolve(result); },
        reject: error => { clearTimeout(timeout); reject(error); } });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }
  async function evaluate(expression) {
    const value = await command('Runtime.evaluate', { expression, returnByValue: true });
    if (value.exceptionDetails) throw new Error(JSON.stringify(value.exceptionDetails));
    return value.result.value;
  }
  readState = () => evaluate('document.body.innerText');
  const browser = await command('Browser.getVersion');
  await command('Network.enable');
  await command('Runtime.enable');
  await command('Page.enable');
  await command('Page.navigate', { url });
  await until(async () => {
    if (failures.length || exceptions.length) throw new Error('Browser failed while loading managed app');
    return (await evaluate('document.querySelector("#count")?.textContent')) === 'Managed count: 0';
  });
  const observed = await evaluate('({revision:document.querySelector("#revision").textContent, architecture:document.querySelector("#architecture").textContent})');
  if (observed.revision !== revision || observed.architecture !== 'Wasm') throw new Error(JSON.stringify(observed));
  // Dispatch through the browser's input pipeline, into Razor's C# @onclick.
  const point = await evaluate('(() => { const r=document.querySelector("#increment").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}; })()');
  for (const count of [1, 2]) {
    await command('Input.dispatchMouseEvent', { type: 'mousePressed', ...point, button: 'left', clickCount: 1 });
    await command('Input.dispatchMouseEvent', { type: 'mouseReleased', ...point, button: 'left', clickCount: 1 });
    await until(async () => (await evaluate('document.querySelector("#count").textContent')) === `Managed count: ${count}`);
  }
  if (!requests.some(request => request.url.endsWith('.wasm') && request.status === 200)) throw new Error('No WebAssembly response');
  if (failures.length || exceptions.length || requests.some(request => request.status >= 400)) {
    throw new Error(JSON.stringify({ failures, exceptions, requests }));
  }
  console.log(JSON.stringify({ browser, revision, architecture: observed.architecture, managedCount: 2, requests, failures, exceptions }, null, 2));
} catch (error) {
  let body;
  try { body = await readState?.(); } catch (stateError) { body = String(stateError); }
  console.error(JSON.stringify({ requests, failures, exceptions, body }, null, 2));
  throw error;
} finally {
  socket?.close();
  if (child.exitCode === null && child.signalCode === null) {
    const exited = new Promise(resolve => child.once('exit', resolve));
    child.kill('SIGTERM');
    await Promise.race([exited, delay(5000)]);
    if (child.exitCode === null && child.signalCode === null) { child.kill('SIGKILL'); await exited; }
  }
  await rm(profile, { recursive: true, force: true });
}
