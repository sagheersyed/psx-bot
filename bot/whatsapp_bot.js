const {
    default: makeWASocket, useMultiFileAuthState, DisconnectReason,
    fetchLatestBaileysVersion, Browsers
} = require('@whiskeysockets/baileys');
const qrcodeTerminal = require('qrcode-terminal');
const QRCode = require('qrcode');
const http = require('http');
const pino = require('pino');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// ---------- config ----------
const ROOT = path.resolve(__dirname, '..');
const DATA_DIR = path.join(ROOT, 'data');
const PID_FILE = path.join(DATA_DIR, 'bot.pid');
const AUTH_DIR = path.join(__dirname, 'auth_session');
const PYTHON = process.env.PYTHON_PATH || 'python';
const ANALYSIS_TIMEOUT_MS = 90_000;
const COOLDOWN_MS = 15_000;                  // same ticker dobara 15s tak nahi
const ONLY_SELF_CHAT = true;                 // sirf "Message Yourself"
const IGNORE_WORDS = new Set(['OK', 'HI', 'HELLO', 'YES', 'NO', 'AOA', 'CALL', 'THANKS', 'THEEK', 'HAAN',
    'KRO', 'KAL', 'BYE', 'WAIT', 'BRO', 'BHAI', 'JI', 'ACHA', 'OKAY', 'NAHI', 'HELP', 'STATS']);

fs.mkdirSync(DATA_DIR, { recursive: true });
fs.writeFileSync(PID_FILE, String(process.pid));
const cleanup = () => { try { fs.unlinkSync(PID_FILE); } catch (e) {} process.exit(0); };
process.on('SIGINT', cleanup); process.on('SIGTERM', cleanup);

const logger = pino({ level: 'silent' });
let latestQR = null, status = 'Starting...', sock = null, reconnectTimer = null;

// ---------- tiny dashboard (QR) — sirf localhost ----------
const page = (body, refresh) => `<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">${refresh ? `<meta http-equiv="refresh" content="${refresh}">` : ''}
<title>PSX Bot</title></head><body style="font-family:sans-serif;background:#0b141a;color:#e9edef;display:flex;
flex-direction:column;align-items:center;justify-content:center;min-height:100vh;text-align:center">${body}</body></html>`;

http.createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    if (req.url === '/reset') {
        fs.rmSync(AUTH_DIR, { recursive: true, force: true });
        latestQR = null; status = 'SESSION_RESET';
        try { sock && sock.end(undefined); } catch (e) {}
        scheduleStart(1000);
        res.writeHead(302, { Location: '/' }); return res.end();
    }
    if (status === 'CONNECTED') return res.end(page(`<h1 style="color:#00a884">✅ WhatsApp Connected</h1>
        <p>"Message Yourself" mein ticker bhejein (OGDC, SYS, LUCK...)</p><a style="color:#ff3860" href="/reset">Unlink</a>`));
    if (!latestQR) return res.end(page(`<h2>⏳ QR tayyar ho raha hai...</h2><p>Status: ${status}</p>`, 2));
    res.end(page(`<h2 style="color:#00a884">PSX Bot link karein</h2>
        <div style="background:#fff;padding:14px;border-radius:12px"><img width="260" src="${latestQR}"></div>
        <p>WhatsApp → Linked Devices → Link a Device</p><a style="color:#8696a0" href="/reset">Reset</a>`, 20));
}).listen(3000, '127.0.0.1', () => console.log('🌐 QR dashboard: http://localhost:3000'))
  .on('error', (e) => console.error('Port 3000 error:', e.message));

// ---------- python analysis (queue + timeout) ----------
let chain = Promise.resolve();
function runPython(args) {
    const job = () => new Promise((resolve, reject) => {
        const proc = spawn(PYTHON, [path.join(ROOT, 'scripts', 'cli_runner.py'), ...args],
            { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
        let out = '', err = '';
        const timer = setTimeout(() => { proc.kill(); reject(new Error('Analysis timeout')); }, ANALYSIS_TIMEOUT_MS);
        proc.stdout.on('data', d => out += d.toString('utf-8'));
        proc.stderr.on('data', d => err += d.toString('utf-8'));
        proc.on('error', e => { clearTimeout(timer); reject(e); });
        proc.on('close', code => {
            clearTimeout(timer);
            if (code === 0 && out.includes('---JSON_OUTPUT_START---')) {
                try { resolve(JSON.parse(out.split('---JSON_OUTPUT_START---')[1].split('---JSON_OUTPUT_END---')[0].trim())); }
                catch (e) { reject(new Error('JSON parse: ' + e.message)); }
            } else reject(new Error(err.slice(-400) || `exit code ${code}`));
        });
    });
    const p = chain.then(job, job);           // ek waqt mein ek analysis
    chain = p.catch(() => {});
    return p;
}

// ---------- bot ----------
function scheduleStart(ms) {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => startBot().catch(console.error), ms);
}
const lastAsked = new Map();

async function startBot() {
    if (sock) { try { sock.ev.removeAllListeners(); sock.end(undefined); } catch (e) {} sock = null; }   // duplicate sockets nahi
    console.log('🚀 PSX Bot start ho raha hai (Privacy: sirf Message Yourself)');
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version } = await fetchLatestBaileysVersion();
    sock = makeWASocket({ version, auth: state, logger, browser: Browsers.windows('Desktop'),
        printQRInTerminal: false, syncFullHistory: false });
    const me = sock;
    me.ev.on('creds.update', saveCreds);

    me.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
        if (me !== sock) return;
        if (qr) {
            status = 'WAITING_FOR_SCAN';
            try { latestQR = await QRCode.toDataURL(qr, { width: 300, margin: 2 }); } catch (e) {}
            console.log('📲 QR scan: http://localhost:3000'); qrcodeTerminal.generate(qr, { small: true });
        }
        if (connection === 'open') { status = 'CONNECTED'; latestQR = null; console.log('✅ WHATSAPP CONNECTED'); }
        if (connection === 'close') {
            const code = lastDisconnect?.error?.output?.statusCode;
            console.log(`⚠️ Connection closed (${code})`);
            if (code === DisconnectReason.loggedOut) {
                fs.rmSync(AUTH_DIR, { recursive: true, force: true });
                latestQR = null; status = 'LOGGED_OUT_NEW_QR'; scheduleStart(2000);
            } else { status = 'DISCONNECTED'; scheduleStart(3000); }
        }
    });

    me.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;
        for (const msg of messages) {
            const jid = msg.key.remoteJid;
            if (!jid || jid === 'status@broadcast' || jid.endsWith('@g.us')) continue;
            const text = (msg.message?.conversation || msg.message?.extendedTextMessage?.text || '').trim();
            if (!text) continue;

            const myNum = me.user?.id?.split(':')[0].replace(/\D/g, '');
            const isSelf = msg.key.fromMe && myNum && jid.replace(/\D/g, '') === myNum;
            if (ONLY_SELF_CHAT && !isSelf) continue;

            const words = text.replace(/^[!/#\s]+/, '').split(/\s+/);
            const low = words[0].toLowerCase();
            if (low === 'help') {
                await me.sendMessage(jid, { text: '🇵🇰 *PSX Smart Bot*\nTicker bhejein: `OGDC`, `SYS`, `LUCK`...\n`stats` — bot ka live win-rate record' });
                continue;
            }
            if (low === 'stats') {
                try { await me.sendMessage(jid, { text: (await runPython(['--stats'])).text }); } catch (e) { console.error(e.message); }
                continue;
            }
            let ticker = words[0].toUpperCase();
            if ((ticker === 'STOCK' || ticker === 'PSX') && words[1]) ticker = words[1].toUpperCase();
            if (!/^[A-Z0-9]{2,8}$/.test(ticker) || IGNORE_WORDS.has(ticker)) continue;

            if (Date.now() - (lastAsked.get(ticker) || 0) < COOLDOWN_MS) continue;
            lastAsked.set(ticker, Date.now());
            try {
                await me.sendMessage(jid, { text: `⏳ *${ticker}* analyze ho raha hai...` });
                const a = await runPython([ticker]);
                await me.sendMessage(jid, { text: a.text });
                if (a.chart_path && fs.existsSync(a.chart_path))
                    await me.sendMessage(jid, { image: { url: a.chart_path }, caption: `📈 ${ticker} chart` });
                console.log(`✅ ${ticker} done`);
            } catch (e) {
                console.error(`❌ ${ticker}:`, e.message);
                await me.sendMessage(jid, { text: `❌ *${ticker}* analyze nahi ho saka. Ticker check karein ya thori der baad try karein.` });
            }
        }
    });
}

startBot().catch(console.error);
