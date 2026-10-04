// Runs the production dispatcher with an in-memory Baileys transport; no WA/network access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { EventEmitter } = require('node:events');
let accept;
const disk = new Map(), sockets = [];
const fakeFs = {
  readFileSync(name) { if (!disk.has(name)) throw Error('missing'); return disk.get(name); },
  mkdirSync() {}, writeFileSync(name, content) { disk.set(name,content); },
  renameSync(from,to) { disk.set(to,disk.get(from)); disk.delete(from); },
};
const baileys = {
  useMultiFileAuthState: async name => ({ state: { name, creds: {} }, saveCreds() {} }),
  fetchLatestBaileysVersion: async () => ({ version: [2,3000,1] }), Browsers: {}, DisconnectReason: { loggedOut: 401 },
  makeWASocket(options) {
    const sock = { name: options.auth.name, ev: new EventEmitter(), ended: false, calls: [],
      async sendMessage(chat,msg) { this.calls.push({chat,msg}); return { key: { id: 'same-message-id' } }; },
      async groupParticipantsUpdate() { return [{ status:'200' }]; }, async groupInviteCode() { return this.name; },
      end() { this.ended = true; }, authState: {creds:{}} };
    sockets.push(sock);
    queueMicrotask(() => sock.ev.emit('connection.update',{connection:'open'}));
    return sock;
  },
};
const context = {
  require(name) {
    if (name === 'pino') return () => ({});
    if (name === '@whiskeysockets/baileys') return baileys;
    if (name.includes('baileys-version')) return {version:[2,3000,1]};
    if (name === 'fs') return fakeFs;
    if (name === 'net') return {createServer(fn) { accept=fn; return {listen(port,host,cb) {cb();}}; }};
    if (name === 'path') return path;
    if (name.includes('isauthvalid')) return {isAuthValid:() => true};
    if (name.includes('resolvebrowser')) return {resolveBrowser:() => ({})};
    if (name === 'qrcode-terminal' || name === 'qrcode') return {};
    throw Error('unexpected module: '+name);
  },
  __dirname: path.resolve(__dirname,'../deploy/wasock'),
  process: {env:{WA_VERSION_TIMEOUT_MS:'0'},cwd:process.cwd}, console:{log(){},error(){}},
  setTimeout, clearTimeout, queueMicrotask,
};
vm.runInNewContext(fs.readFileSync(path.resolve(__dirname,'../deploy/wasock/server.js'),'utf8'),context);
function client() { const c = new EventEmitter(); c.destroyed=false; c.responses=[]; c.write = line => c.responses.push(JSON.parse(line)); accept(c); return c; }
async function request(c,message) { c.emit('data',Buffer.from(JSON.stringify(message)+'\n')); for(let i=0;i<6;i++) await new Promise(resolve => setImmediate(resolve)); return c.responses.filter(r=>r.type==='response').at(-1); }
(async () => {
  const a=client(),b=client();
  await Promise.all([request(a,{action:'setup',authName:'account-a'}),request(b,{action:'setup',authName:'account-b'})]);
  await Promise.all([request(a,{action:'start'}),request(b,{action:'start'})]);
  assert.equal(sockets.length,2);
  const sa=sockets.find(s=>s.name===path.resolve('account-a')),sb=sockets.find(s=>s.name===path.resolve('account-b'));
  assert.equal(sa.ended,false); assert.equal(sb.ended,false);
  assert.equal((await request(client(),{action:'sendMessage',authName:'account-a',chat:'contact',msg:'A'})).success,true);
  assert.equal((await request(client(),{action:'sendMessage',authName:'account-b',chat:'contact',msg:'B'})).success,true);
  assert.equal(sa.calls[0].msg.text,'A'); assert.equal(sb.calls[0].msg.text,'B');
  assert.equal((await request(client(),{action:'sendMessage',chat:'contact',msg:'no-owner'})).success,false);
  const duplicate=client(); await request(duplicate,{action:'setup',authName:'account-a'}); await request(duplicate,{action:'start'});
  assert.equal(sockets.length,2,'same account must reuse its connection');
  a.responses=[]; b.responses=[];
  sa.ev.emit('messages.upsert',{messages:[{text:'only-A'}]});
  assert.equal(a.responses[0].authName,path.resolve('account-a')); assert.equal(b.responses.length,0);
  sa.ev.emit('messages.update',[{key:{fromMe:true,id:'same-message-id',remoteJid:'contact'},update:{status:4}}]);
  sb.ev.emit('messages.update',[{key:{fromMe:true,id:'same-message-id',remoteJid:'contact'},update:{status:3}}]);
  const receipts=(await request(client(),{action:'getReceipts'})).receipts;
  assert.equal(receipts.length,2); assert.equal(receipts.find(r=>r.auth_name===sa.name).status,'read'); assert.equal(receipts.find(r=>r.auth_name===sb.name).status,'delivered');
  a.destroyed=true;a.emit('close'); assert.equal(sa.ended,false,'closing one event listener must not disconnect the account');
  await request(client(),{action:'stop',authName:'account-a'});
  assert.equal(sa.ended,true);assert.equal(sb.ended,false);
  assert.equal((await request(client(),{action:'sendMessage',authName:'account-b',chat:'contact',msg:'still-online'})).success,true);
  assert.equal((await request(client(),{action:'listSessions'})).sessions.find(s=>s.auth_name===sa.name).status,'idle');
  console.log('PASS: two concurrent accounts, targeted send, shared-account reuse, isolated events/receipts, targeted stop');
})().catch(error => {console.error(error);process.exitCode=1;});
