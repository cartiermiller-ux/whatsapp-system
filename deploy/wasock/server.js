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

// ---------- 代理支持 ----------
// 国内服务器直连 web.whatsapp.com 会被黑洞（TCP 握手超时），必须走代理。
// 通过环境变量开启：
//     WA_PROXY_URL=http://127.0.0.1:7890        HTTP CONNECT 代理
//     WA_PROXY_URL=socks5://127.0.0.1:10808     SOCKS5（需额外装 socks-proxy-agent）
// https-proxy-agent 已在 wasock 依赖里，HTTP 代理开箱可用。
const PROXY_URL = process.env.WA_PROXY_URL || "";

function buildProxyAgent() {
    if (!PROXY_URL) {
        return null;
    }
    try {
        if (/^socks/i.test(PROXY_URL)) {
            const { SocksProxyAgent } = require("socks-proxy-agent");
            console.log("[proxy] 已启用 SOCKS5 代理:", PROXY_URL);
            return new SocksProxyAgent(PROXY_URL);
        }
        const { HttpsProxyAgent } = require("https-proxy-agent");
        console.log("[proxy] 已启用 HTTP 代理:", PROXY_URL);
        return new HttpsProxyAgent(PROXY_URL);
    } catch (err) {
        console.error("[proxy] 初始化失败，将直连:", err.message);
        return null;
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

    const override = (process.env.WA_BAILEYS_VERSION || "").trim();
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
    const raw = (process.env.WA_VERSION_TIMEOUT_MS || "5000").trim();
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

var loggerLevel = "silent";
var authName = "auth";
var browserInfo = ["ubuntu", "Chrome", "14.4.1"];
var syncFullHistory = false;

var globalSocket;

function send(socket, message) {
    socket.write(JSON.stringify(message) + "\n");
}

const authPath = path.resolve(authName);
if (fs.existsSync(authPath) && !isAuthValid(authPath)) {
    fs.rmSync(authPath, { recursive: true, force: true });
}

async function startBaileys(logger, authName, browserInfo, socket) {
    const { state, saveCreds } = await useMultiFileAuthState(authName);
    const version = await resolveBaileysVersion();

    const sock = makeWASocket({
        auth: state,
        logger,
        version,
        browser: resolveBrowser(browserInfo, Browsers),
        syncFullHistory,
        // 只有配了代理才传，避免给 ws 库塞 null
        ...(proxyAgent ? { agent: proxyAgent, fetchAgent: proxyAgent } : {}),
    });
    globalSocket = sock;

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("connection.update", async (update) => {
        const { qr, connection, lastDisconnect } = update;

        if (qr) {
            send(socket, {
                type: "event",
                event: "login",
                qr
            });
        }

        switch (connection) {
            case "open":
                send(socket, {
                    type: "event",
                    event: "connection",
                    status: "open"
                });
                break;

            case "close":
                const shouldReconnect = lastDisconnect?.error?.output?.statusCode;

                send(socket, {
                    type: "event",
                    event: "connection",
                    status: "close",
                    reason: lastDisconnect?.error?.message,
                    statusCode: shouldReconnect
                });

                if (shouldReconnect !== DisconnectReason.loggedOut) {
                    await startBaileys(logger, authName, browserInfo, socket);
                }

                break;
        }
    });

    sock.ev.on("messages.upsert", (update) => {
        send(socket, {
            type: "event",
            event: "message",
            message: update
        });
    });
}

const server = net.createServer((socket) => {
    let buffer = "";
    let processing = false;
    const queue = [];

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
                loggerLevel = message.loggerLevel;
                authName = message.authName;
                syncFullHistory = message.syncFullHistory;
                browserInfo = message.browserInfo;
                send(socket, { type: "response", success: true, message: "" });
            }

            if (message.action === "start") {
                await startBaileys(pino({ level: loggerLevel }), authName, browserInfo, socket);
                send(socket, { type: "response", success: true, message: "" });
            }

            if (message.action === "replyMessage") {
                try {
                    if (!globalSocket) throw new Error("Not connected");
                    if (!message.chat) throw new Error("chat is required");

                    await globalSocket.sendMessage(
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
                    if (!globalSocket) throw new Error("Not connected");
                    await globalSocket.sendMessage(
                        message.chat,
                        { text: message.msg },
                    );
                    send(socket, { type: "response", success: true, message: "" });
                } catch (err) {
                    console.error("sendMessage error:", err);
                    send(socket, { type: "response", success: false, message: err.message });
                }
            }

            if (message.action === "deleteMessage") {
                try {
                    if (!globalSocket) throw new Error("Not connected");
                    await globalSocket.sendMessage(
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
                    if (!globalSocket) throw new Error("Not connected");
                    if (globalSocket.authState.creds.registered) {
                        throw new Error("Already registered, no need for pairing code");
                    }
                    
                    const code = message.customPairingCode
                        ? await globalSocket.requestPairingCode(message.phoneNumber, message.customPairingCode)
                        : await globalSocket.requestPairingCode(message.phoneNumber);

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
const PORT = Number(process.env.WA_PORT || 5000);

server.listen(PORT, () => {
    console.log("Server running on " + PORT + " port");
});