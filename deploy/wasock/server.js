const pino = require("pino");
const {
    makeWASocket,
    fetchLatestBaileysVersion,
    useMultiFileAuthState,
    DisconnectReason,
    Browsers
} = require("@whiskeysockets/baileys");
const qrcode = require("qrcode-terminal");
const QRcode = require("qrcode");
const fs = require("fs");
const path = require("path");
const net = require("net");

const { isAuthValid } = require("./assets/isauthvalid");
const { resolveBrowser } = require("./assets/resolvebrowser");

// ---------- 配置来源：环境变量 或 项目目录下的 .env ----------
// 后端拉起这个进程时会透传环境变量；但如果后端是在配置之前启动的（进程里还留着
// 旧的 os.environ），环境变量就是空的。所以这里自己再读一遍项目根目录的 .env，
// 保证「谁拉起它都能拿到代理配置」。
function readEnvFile() {
    const candidates = [
        path.resolve(__dirname, "..", "..", ".env"),   // deploy/wasock/ -> 项目根
        path.resolve(process.cwd(), ".env"),
    ];
    const data = {};
    for (const file of candidates) {
        let text;
        try {
            text = fs.readFileSync(file, "utf8");
        } catch (err) {
            continue;
        }
        for (const raw of text.split(/\r?\n/)) {
            const line = raw.trim();
            if (!line || line.startsWith("#")) continue;
            const eq = line.indexOf("=");
            if (eq < 0) continue;
            let key = line.slice(0, eq).trim();
            if (key.startsWith("export ")) key = key.slice(7).trim();
            let value = line.slice(eq + 1).trim();
            if (value.length >= 2 && (value[0] === '"' || value[0] === "'")
                && value[value.length - 1] === value[0]) {
                value = value.slice(1, -1);
            }
            if (key && !(key in data)) data[key] = value;
        }
    }
    return data;
}

const ENV_FILE = readEnvFile();

function config(name, fallback) {
    const fromProcess = process.env[name];
    if (fromProcess !== undefined && fromProcess !== "") return fromProcess;
    const fromFile = ENV_FILE[name];
    if (fromFile !== undefined && fromFile !== "") return fromFile;
    return fallback === undefined ? "" : fallback;
}

// ---------- 代理支持 ----------
// 国内服务器直连 web.whatsapp.com 会被黑洞（TCP 握手超时），必须走代理。
// 配置方式（环境变量优先，其次项目目录下的 .env）：
//     WA_PROXY_URL=http://127.0.0.1:7890        HTTP CONNECT 代理
//     WA_PROXY_URL=socks5://127.0.0.1:10808     SOCKS5（需额外装 socks-proxy-agent）
// https-proxy-agent 已在 wasock 依赖里，HTTP 代理开箱可用。
const PROXY_URL = String(config("WA_PROXY_URL", "")).trim();

function buildProxyAgent(proxyUrl = PROXY_URL) {
    if (!proxyUrl) {
        return null;
    }
    try {
        if (/^socks/i.test(proxyUrl)) {
            const { SocksProxyAgent } = require("socks-proxy-agent");
            console.log("[proxy] 已启用 SOCKS5 代理");
            return new SocksProxyAgent(proxyUrl);
        }
        const { HttpsProxyAgent } = require("https-proxy-agent");
        console.log("[proxy] 已启用 HTTP 代理");
        return new HttpsProxyAgent(proxyUrl);
    } catch (err) {
        throw new Error("代理初始化失败，请检查代理配置与依赖");
    }
}

const proxyAgent = buildProxyAgent();

// ---------- 版本号获取 ----------
// Baileys 的 fetchLatestBaileysVersion() 会去 raw.githubusercontent.com 拉版本号。
// 国内服务器上这个域名可能被黑洞：TCP 连接既不成功也不报错，Promise 永远不 resolve，
// 而 server.js 的 start 分支是 await 之后才回包 —— 结果就是「扫码一直转圈」。
// 这里加硬超时 + 走代理 + 回退到 Baileys 内置版本，保证 start 一定能在几秒内回包。
let BUNDLED_VERSION = [2, 3000, 1015901307];
try {
    BUNDLED_VERSION = require("@whiskeysockets/baileys/lib/Defaults/baileys-version.json").version;
} catch (err) {
    console.log("[version] 读取内置版本失败，使用兜底值:", err.message);
}

function withTimeout(promise, ms, label) {
    let timer;
    const guard = new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(label + " 超时 " + ms + "ms")), ms);
    });
    return Promise.race([promise, guard]).finally(() => clearTimeout(timer));
}

let cachedVersion = null;

async function resolveBaileysVersion() {
    // 断线重连会反复调用 startBaileys，不能每次都去网上拉版本
    if (cachedVersion) {
        return cachedVersion;
    }

    const override = String(config("WA_BAILEYS_VERSION", "")).trim();
    if (override) {
        const parts = override.split(".").map((n) => Number(n));
        if (parts.length === 3 && parts.every((n) => Number.isInteger(n) && n >= 0)) {
            console.log("[version] 使用环境变量指定版本:", parts.join("."));
            cachedVersion = parts;
            return parts;
        }
        console.log("[version] WA_BAILEYS_VERSION 格式不对，忽略:", override);
    }

    // WA_VERSION_TIMEOUT_MS=0 表示完全不联网取版本，直接用 Baileys 内置版本
    const raw = String(config("WA_VERSION_TIMEOUT_MS", "5000")).trim();
    const timeoutMs = Number(raw);
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
        console.log("[version] 已跳过在线获取，使用内置版本:", BUNDLED_VERSION.join("."));
        cachedVersion = BUNDLED_VERSION;
        return BUNDLED_VERSION;
    }

    const options = { timeout: timeoutMs };
    if (proxyAgent) {
        // axios 在给了 httpsAgent 时不应再走自身的 proxy 逻辑
        options.httpsAgent = proxyAgent;
        options.proxy = false;
    }

    try {
        const result = await withTimeout(
            fetchLatestBaileysVersion(options),
            timeoutMs + 1000,
            "获取在线版本"
        );
        if (result && !result.error && Array.isArray(result.version)) {
            console.log("[version] 在线版本:", result.version.join("."));
            cachedVersion = result.version;
            return result.version;
        }
        console.log(
            "[version] 在线获取失败，回退内置版本:",
            BUNDLED_VERSION.join("."),
            "|",
            String((result && result.error && result.error.message) || "unknown")
        );
        cachedVersion = BUNDLED_VERSION;
        return BUNDLED_VERSION;
    } catch (err) {
        console.log("[version] 在线获取异常，回退内置版本:", BUNDLED_VERSION.join("."), "|", err.message);
        cachedVersion = BUNDLED_VERSION;
        return BUNDLED_VERSION;
    }
}

// Each auth directory owns one connection, receipt store and event subscribers.
const sessions = new Map();
function send(socket, message) {
    if (!socket.destroyed) socket.write(JSON.stringify(message) + "\n");
}
function publish(entry, message) {
    for (const client of entry.clients) send(client, { ...message, authName: entry.name });
}
function recordReceipt(entry, key, status) {
    if (!key?.fromMe || !key.id || !key.remoteJid) return;
    const id = key.remoteJid + ":" + key.id;
    const previous = entry.receipts[id];
    if (previous?.status === "read" || previous?.status === status) return;
    entry.receipts[id] = { message_id: key.id, target: key.remoteJid, status, auth_name: entry.name };
    const dest = path.join(entry.name, "receipts.json");
    try {
        fs.mkdirSync(entry.name, { recursive: true });
        fs.writeFileSync(dest + ".tmp", JSON.stringify(entry.receipts), { mode: 0o600 });
        fs.renameSync(dest + ".tmp", dest);
    } catch { console.error("receipt persistence failed"); }
}
function getEntry(message, client, allowMissing = false) {
    const name = message.authName || client.authName;
    if (name) {
        const entry = sessions.get(path.resolve(name));
        if (!entry && !allowMissing) throw new Error("Account session is not started");
        return entry;
    }
    const connected = [...sessions.values()].filter(entry => entry.sock && !entry.stopped);
    if (connected.length !== 1) throw new Error("authName is required when multiple account sessions exist");
    return connected[0];
}
function stopEntry(entry) {
    if (!entry) return;
    entry.stopped = true;
    entry.status = "idle";
    entry.qr = "";
    clearTimeout(entry.retry); entry.retry = null;
    if (entry.sock) {
        entry.sock.ev.removeAllListeners("connection.update");
        entry.sock.end(new Error("Account session stopped"));
        entry.sock = null;
    }
    publish(entry, { type: "event", event: "connection", status: "stopped" });
}
async function connectEntry(entry) {
    if (entry.stopped) return;
    const selectedAgent = buildProxyAgent(entry.config.proxyUrl);
    const { state, saveCreds } = await useMultiFileAuthState(entry.name);
    const version = await resolveBaileysVersion();
    if (entry.stopped) return;
    const sock = makeWASocket({
        auth: state, logger: pino({ level: entry.config.loggerLevel }), version,
        browser: resolveBrowser(entry.config.browserInfo, Browsers),
        syncFullHistory: entry.config.syncFullHistory,
        ...(selectedAgent ? { agent: selectedAgent, fetchAgent: selectedAgent } : {}),
    });
    entry.sock = sock;
    sock.ev.on("creds.update", () => { if (entry.sock === sock && !entry.stopped) saveCreds(); });
    sock.ev.on("connection.update", update => {
        if (entry.sock !== sock || entry.stopped) return;
        const { qr, connection, lastDisconnect } = update;
        if (qr) {
            entry.status = "waiting_qr"; entry.qr = qr;
            publish(entry, { type: "event", event: "login", qr });
        }
        if (connection === "open") {
            entry.status = "connected"; entry.qr = ""; entry.retryCount = 0;
            publish(entry, { type: "event", event: "connection", status: "open" });
        } else if (connection === "close") {
            entry.status = "closed"; entry.sock = null;
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            publish(entry, { type: "event", event: "connection", status: "close", statusCode,
                reason: lastDisconnect?.error?.message });
            sock.ev.removeAllListeners("connection.update");
            if (statusCode !== DisconnectReason.loggedOut && !entry.stopped) {
                entry.retryCount += 1;
                entry.retry = setTimeout(() => { entry.retry = null; connectEntry(entry).catch(() => {
                    entry.status = "error";
                    publish(entry, { type: "event", event: "connection", status: "close", reason: "Account reconnect failed" });
                }); }, Math.min(30000, 1000 * 2 ** Math.min(entry.retryCount, 5)));
            }
        }
    });
    sock.ev.on("messages.update", updates => {
        if (entry.sock !== sock || entry.stopped) return;
        for (const { key, update } of updates) {
            if (update.status >= 4) recordReceipt(entry, key, "read");
            else if (update.status === 3) recordReceipt(entry, key, "delivered");
        }
    });
    sock.ev.on("message-receipt.update", updates => {
        if (entry.sock !== sock || entry.stopped) return;
        for (const { key, receipt } of updates) {
            if (receipt.readTimestamp || receipt.playedTimestamp) recordReceipt(entry, key, "read");
            else if (receipt.receiptTimestamp) recordReceipt(entry, key, "delivered");
        }
    });
    sock.ev.on("messages.upsert", message => { if (entry.sock === sock && !entry.stopped) publish(entry, { type: "event", event: "message", message }); });
}
async function startBaileys(config, client) {
    const name = path.resolve(config.authName);
    client.authName = name;
    let entry = sessions.get(name);
    if (!entry) {
        let receipts = {};
        try { receipts = JSON.parse(fs.readFileSync(path.join(name, "receipts.json"), "utf8")); } catch { }
        entry = { name, config, receipts, clients: new Set(), sock: null, status: "starting",
            qr: "", stopped: false, retryCount: 0, pending: null };
        sessions.set(name, entry);
    }
    if ((entry.sock || entry.pending || entry.retry) && entry.config.proxyUrl !== config.proxyUrl) {
        throw new Error("Stop this account before changing its proxy");
    }
    entry.clients.add(client);
    if (entry.pending) await entry.pending;
    else if (!entry.sock && !entry.retry) {
        entry.config = config; entry.stopped = false; entry.status = "starting";
        entry.pending = connectEntry(entry);
        try { await entry.pending; }
        catch (err) { entry.status = "error"; throw err; }
        finally { entry.pending = null; }
    } else if (entry.config.proxyUrl !== config.proxyUrl) {
        throw new Error("Stop this account before changing its proxy");
    }
    return entry;
}

const server = net.createServer((socket) => {
    let buffer = "";
    let processing = false;
    const settings = { authName: "auth", loggerLevel: "silent", browserInfo: ["ubuntu", "Chrome", "14.4.1"],
        syncFullHistory: false, proxyUrl: PROXY_URL };
    socket.on("close", () => { for (const entry of sessions.values()) entry.clients.delete(socket); });

    async function processBuffer() {
        if (processing) return;
        processing = true;

        while (buffer.includes("\n")) {
            const index = buffer.indexOf("\n");
            const line = buffer.slice(0, index);
            buffer = buffer.slice(index + 1);

            if (!line) continue;

            let message;
            try {
                message = JSON.parse(line);
            } catch (e) {
                console.log("Invalid JSON:", line);
                continue;
            }

            if (message.action === "setup") {
                settings.loggerLevel = message.loggerLevel || "silent";
                settings.authName = message.authName || "auth";
                settings.proxyUrl = message.proxyUrl === undefined ? PROXY_URL : String(message.proxyUrl || "");
                settings.syncFullHistory = Boolean(message.syncFullHistory);
                settings.browserInfo = message.browserInfo || ["ubuntu", "Chrome", "14.4.1"];
                socket.authName = path.resolve(settings.authName);
                send(socket, { type: "response", success: true, message: "", multi_session: true });
            }

            if (message.action === "start") {
                try {
                    const entry = await startBaileys(settings, socket);
                    send(socket, { type: "response", success: true, message: "", status: entry.status, qr: entry.qr });
                } catch (err) { send(socket, { type: "response", success: false, message: err.message }); }
            }

            if (message.action === "capabilities") {
                send(socket, { type: "response", success: true, multi_session: true, protocol_version: 2 });
            }
            if (message.action === "stop") {
                try { stopEntry(getEntry(message, socket, true)); send(socket, { type: "response", success: true }); }
                catch (err) { send(socket, { type: "response", success: false, message: err.message }); }
            }
            if (message.action === "listSessions") {
                send(socket, { type: "response", success: true, sessions: [...sessions.values()].map(entry => ({ auth_name: entry.name, status: entry.status })) });
            }
            if (message.action === "replyMessage") {
                try {
                    const entry = getEntry(message, socket);
                    const accountSocket = entry.sock;
                    if (!accountSocket || entry.status !== "connected") throw new Error("Account is not connected");
                    if (!message.chat) throw new Error("chat is required");

                    await accountSocket.sendMessage(
                        message.chat,
                        { text: message.msg },
                        { quoted: message.quoted }
                    );
                    send(socket, { type: "response", success: true, message: "" });
                } catch (err) {
                    console.error("replyMessage error:", err.message);
                    send(socket, { type: "response", success: false, message: err.message });
                }
            } 

            if (message.action === "sendMessage") {
                try {
                    const entry = getEntry(message, socket);
                    const accountSocket = entry.sock;
                    if (!accountSocket || entry.status !== "connected") throw new Error("Account is not connected");
                    const result = await accountSocket.sendMessage(
                        message.chat,
                        { text: message.msg },
                    );
                    send(socket, { type: "response", success: true, message: "", message_id: result?.key?.id || "" });
                } catch (err) {
                    console.error("sendMessage error:", err);
                    send(socket, { type: "response", success: false, message: err.message });
                }
            }

            if (message.action === "addParticipants") {
                try {
                    const entry = getEntry(message, socket);
                    const accountSocket = entry.sock;
                    if (!accountSocket || entry.status !== "connected") throw new Error("Account is not connected");
                    const results = await accountSocket.groupParticipantsUpdate(message.chat, message.participants, "add");
                    const success = results.length > 0 && results.every(item => String(item.status) === "200");
                    send(socket, { type: "response", success, results,
                        message: success ? "" : "拉群未成功：" + results.map(item => item.status).join(", ") });
                } catch (err) { send(socket, { type: "response", success: false, message: err.message }); }
            }
            if (message.action === "groupInviteCode") {
                try {
                    const entry = getEntry(message, socket);
                    const accountSocket = entry.sock;
                    if (!accountSocket || entry.status !== "connected") throw new Error("Account is not connected");
                    const code = await accountSocket.groupInviteCode(message.chat);
                    send(socket, { type: "response", success: Boolean(code), code, message: code ? "" : "无法获取群链接" });
                } catch (err) { send(socket, { type: "response", success: false, message: err.message }); }
            }
            if (message.action === "getReceipts") {
                const selected = message.authName ? [sessions.get(path.resolve(message.authName))].filter(Boolean) : [...sessions.values()];
                const all = selected.flatMap(entry => Object.values(entry.receipts).map(receipt => ({ ...receipt, auth_name: entry.name })));
                const offset = Math.max(0, Number(message.offset) || 0);
                const limit = Math.min(500, Math.max(1, Number(message.limit) || 500));
                send(socket, { type: "response", success: true, receipts: all.slice(offset, offset + limit),
                    next_offset: offset + limit < all.length ? offset + limit : null });
            }

            if (message.action === "deleteMessage") {
                try {
                    const entry = getEntry(message, socket);
                    const accountSocket = entry.sock;
                    if (!accountSocket || entry.status !== "connected") throw new Error("Account is not connected");
                    await accountSocket.sendMessage(
                        message.chat,
                        { delete: message.key },
                    );
                    send(socket, { type: "response", success: true, message: "" });
                } catch (err) {
                    console.error("deleteMessage error:", err);
                    send(socket, { type: "response", success: false, message: err.message });
                }
            }

            if (message.action === "qrcodeGenerate") {
                if (message.type === "img") {
                    QRcode.toFile(message.fileName, message.qr, { width: message.fileWidth }, (err) => {
                        if (err) {
                            send(socket, { type: "response", success: false, message: err.message });
                            return;
                        }

                        send(socket, { type: "response", success: true, message: "" });
                    });
                } else if (message.type === "terminal") {
                    qrcode.generate(message.qr, { small: message.small });
                    send(socket, { type: "response", success: true, message: "" });
                }
            }

            if (message.action === "requestPairCode") {
                try {
                    const entry = getEntry(message, socket);
                    const accountSocket = entry.sock;
                    if (!accountSocket) throw new Error("Account is not started");
                    if (accountSocket.authState.creds.registered) {
                        throw new Error("Already registered, no need for pairing code");
                    }
                    
                    const code = message.customPairingCode
                        ? await accountSocket.requestPairingCode(message.phoneNumber, message.customPairingCode)
                        : await accountSocket.requestPairingCode(message.phoneNumber);

                    send(socket, { type: "response", success: true, message: "", code });
                } catch (err) {
                    console.error("requestParinigCode error:", err);
                    send(socket, { type: "response", success: false, message: err.message });
                }
            }
        }

        processing = false;
    }

    socket.on("data", (data) => {
        buffer += data.toString();
        processBuffer();
    });
});

// 端口可用 WA_PORT 覆盖（默认 5000，与 wasock 保持一致）
const PORT = Number(config("WA_PORT", "5000") || 5000);

server.listen(PORT, "127.0.0.1", () => {
    console.log("Server running on " + PORT + " port");
});