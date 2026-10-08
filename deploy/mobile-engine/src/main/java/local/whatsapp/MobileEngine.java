package local.whatsapp;

import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import it.auties.whatsapp.api.*;
import it.auties.whatsapp.controller.*;
import it.auties.whatsapp.model.companion.*;
import it.auties.whatsapp.model.jid.Jid;
import it.auties.whatsapp.model.mobile.*;
import it.auties.whatsapp.model.signal.auth.UserAgent.PlatformType;
import it.auties.whatsapp.model.signal.auth.Version;
import it.auties.whatsapp.model.signal.keypair.*;
import java.io.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

/** One JVM, isolated persistent session per tenant/account. Secrets travel through stdin only. */
public final class MobileEngine {
    private static final Map<String, Session> SESSIONS = new ConcurrentHashMap<>();
    private static final PrintWriter OUT = new PrintWriter(new OutputStreamWriter(System.out, StandardCharsets.UTF_8), true);
    private static final Path ROOT = Path.of(System.getenv().getOrDefault("WA_MOBILE_AUTH_ROOT", "whatsapp_auth/mobile")).toAbsolutePath().normalize();
    private static class Session {
        volatile String status = "idle", error = "", phone = "";
        Whatsapp api;
        boolean stopped;
        long generation;
        Map<String,Object> snapshot() { return Map.of("status", status, "error", error, "phone", phone); }
    }
    private static synchronized void output(Object value) { OUT.println(JSON.toJSONString(value)); }
    private static void event(String name, Session session) { output(Map.of("event", "connection", "session", name, "data", session.snapshot())); }
    private static byte[] decode(JSONObject json, String key) { return Base64.getDecoder().decode(json.getString(key)); }
    private static SignalKeyPair pair(JSONObject json, String publicName, String privateName) {
        return new SignalKeyPair(decode(json, publicName), decode(json, privateName));
    }

    private static Whatsapp importClient(String name, JSONObject request, Session session) throws Exception {
        Path directory = ROOT.resolve(name).normalize();
        if (!directory.startsWith(ROOT)) throw new IllegalArgumentException();
        Files.createDirectories(directory);
        ControllerSerializer serializer = ControllerSerializer.toProtobuf(directory);
        Object credentials = request.get("credentials");
        String format = request.getString("format");
        String number = request.getString("phone");
        PhoneNumber phone = PhoneNumber.of(number).orElseThrow();
        var restored = serializer.deserializeStoreKeysPair(null, phone, null, ClientType.MOBILE);
        Store store;
        Keys keys;
        if (restored.isPresent()) {
            store = restored.get().store(); keys = restored.get().keys();
        } else {
            UUID uuid = UUID.nameUUIDFromBytes(name.getBytes(StandardCharsets.UTF_8));
            if ("full_params".equals(format)) {
                JSONObject data = (JSONObject) credentials;
                // Account storage UUID is tenant scoped; phone/device UUIDs stay in device identity fields.
                keys = new KeysBuilder().uuid(uuid).phoneNumber(phone).clientType(ClientType.MOBILE)
                    .registrationId(data.getIntValue("registrationID"))
                    .noiseKeyPair(pair(data, "clientStaticPublicKey", "clientStaticPrivateKey"))
                    .identityKeyPair(pair(data, "identityPublicKey", "identityPrivateKey"))
                    .signedKeyPair(new SignalSignedKeyPair(data.getIntValue("signPreKeyID"), decode(data,"signPreKeyPublicKey"), decode(data,"signPreKeyPrivateKey"), decode(data,"signPreKeySignature")))
                    .fdid(data.getString("phoneUUID"))
                    .deviceId(uuidBytes(UUID.fromString(data.getString("deviceUUID"))))
                    // This SDK field is used for registration, which imported registered accounts skip.
                    .identityId(data.containsKey("identityId") ? decode(data,"identityId") : uuidBytes(UUID.fromString(data.getString("deviceUUID"))))
                    .registered(true).build();
                store = Store.of(uuid, phone, null, ClientType.MOBILE);
                store.setDevice(new CompanionDeviceBuilder().model(data.getString("device"))
                    .manufacturer(data.getString("manufacturer"))
                    .platform("business".equals(request.getString("account_type")) ? PlatformType.ANDROID_BUSINESS : PlatformType.ANDROID)
                    .appVersion(Version.of(data.getString("whatsappVersion")))
                    .osVersion(Version.of(data.getString("osVersion")))
                    .osBuildNumber(data.getString("osBuildNumber"))
                    .modelId(data.getString("roProductDevice")).clientType(ClientType.MOBILE).build());
                CountryLocale.of(data.getString("language") + "-" + data.getString("country")).ifPresent(store::setLocale);
            } else if ("six_segment".equals(format)) {
                var six = SixPartsKeys.of(String.join(",", ((com.alibaba.fastjson2.JSONArray) credentials).toJavaList(String.class)));
                if (!six.phoneNumber().equals(phone)) throw new IllegalArgumentException();
                keys = new KeysBuilder().uuid(uuid).phoneNumber(phone).clientType(ClientType.MOBILE)
                    .noiseKeyPair(six.noiseKeyPair()).identityKeyPair(six.identityKeyPair()).identityId(six.identityId()).registered(true).build();
                store = Store.of(uuid, phone, null, ClientType.MOBILE);
                // Six-part files carry no hardware/version; preserve the SDK's persisted mobile profile.
                String version = System.getenv("WA_MOBILE_SIX_VERSION");
                store.setDevice(CompanionDevice.ios(version == null || version.isBlank() ? null : Version.of(version), "business".equals(request.getString("account_type")), (List<String>)null));
            } else throw new IllegalArgumentException();
            keys.setSerializer(serializer); store.setSerializer(serializer);
            store.setJid(Jid.of(number));
            serializer.linkMetadata(store);
            keys.serialize(false); store.serialize(false);
        }
        if (!keys.phoneNumber().orElseThrow().equals(phone)) throw new IllegalArgumentException();
        String proxy = request.getString("proxy");
        store.setProxy(proxy == null || proxy.isBlank() ? null : URI.create(proxy));
        store.setTextPreviewSetting(TextPreviewSetting.DISABLED);
        var api = Whatsapp.customBuilder().keys(keys).store(store).errorHandler((client, location, error) -> {
            session.error = "protocol_" + location.name().toLowerCase(Locale.ROOT);
            session.status = "error"; event(name,session);
            return ErrorHandler.Result.DISCONNECT;
        }).build();
        api.addLoggedInListener(() -> {
            synchronized(session) {
                if (session.stopped) return;
                session.phone = api.store().jid().map(Jid::user).orElse("");
                session.status = number.equals(session.phone) ? "connected" : "error";
                session.error = number.equals(session.phone) ? "" : "phone_mismatch";
                event(name,session);
            }
        });
        api.addDisconnectedListener(reason -> {
            synchronized(session) {
                if (!session.stopped && !session.status.equals("error")) {
                    session.status = "closed"; session.error = "disconnect_" + reason.name().toLowerCase(Locale.ROOT);
                }
                event(name,session);
            }
        });
        return api;
    }
    private static byte[] uuidBytes(UUID uuid) {
        return java.nio.ByteBuffer.allocate(16).putLong(uuid.getMostSignificantBits()).putLong(uuid.getLeastSignificantBits()).array();
    }

    private static Object command(JSONObject request) throws Exception {
        String action = request.getString("action");
        if ("health".equals(action)) return Map.of("ready",true,"engine","cobalt-0.0.10");
        String name = request.getString("session");
        if (name == null || !name.matches("t[0-9]+-a[0-9]+")) throw new IllegalArgumentException();
        Session session = SESSIONS.computeIfAbsent(name, ignored -> new Session());
        synchronized(session) {
            switch(action) {
                case "connect" -> {
                    if (session.status.equals("connected") || session.status.equals("starting")) return session.snapshot();
                    if (session.api == null) session.api = importClient(name,request,session);
                    session.stopped=false; session.status="starting"; session.error="";
                    long generation=++session.generation;
                    session.api.connect().orTimeout(60,TimeUnit.SECONDS).whenComplete((api,error) -> {
                        synchronized(session) {
                            if (error != null && !session.stopped && generation == session.generation) {
                                session.status="error";session.error="login_failed";event(name,session);
                                session.api.disconnect();
                            }
                        }
                    });
                    return session.snapshot();
                }
                case "status" -> { return session.snapshot(); }
                case "validate" -> {
                    if(session.api == null) session.api = importClient(name,request,session);
                    return Map.of("validated",true,"registration_id",session.api.keys().registrationId(),"device",session.api.store().device().model());
                }
                case "disconnect" -> {
                    session.stopped=true; ++session.generation;
                    if (session.api != null) session.api.disconnect();
                    session.status="idle";session.error="";session.phone="";event(name,session);
                    return session.snapshot();
                }
                case "presence" -> {
                    if (!session.status.equals("connected")) throw new IllegalStateException();
                    session.api.changePresence(request.getBooleanValue("available")).get(20,TimeUnit.SECONDS);
                    return Map.of("success",true);
                }
                case "send" -> {
                    if (!session.status.equals("connected")) throw new IllegalStateException();
                    var message=session.api.sendMessage(Jid.of(request.getString("target")), request.getString("text")).get(30,TimeUnit.SECONDS);
                    return Map.of("success",true,"message_id",message.id());
                }
                default -> throw new IllegalArgumentException();
            }
        }
    }
    public static void main(String[] args) throws Exception {
        Files.createDirectories(ROOT);
        Runtime.getRuntime().addShutdownHook(new Thread(() -> SESSIONS.values().forEach(s -> {if(s.api!=null) s.api.disconnect();})));
        try (var input=new BufferedReader(new InputStreamReader(System.in,StandardCharsets.UTF_8))) {
            String line;
            while ((line=input.readLine()) != null) {
                if(line.length()>2_000_000) continue;
                JSONObject request;
                try {request=JSON.parseObject(line);}catch(Exception ignored){continue;}
                Thread.startVirtualThread(() -> {
                    String id=request.getString("id");
                    try { output(Map.of("id",id,"ok",true,"data",command(request))); }
                    catch(Throwable error) {
                        if ("true".equals(System.getenv("WA_MOBILE_TEST_DIAGNOSTICS"))) {
                            System.err.println(error.getClass().getName());
                            for(var frame:error.getStackTrace()) System.err.println(frame);
                        }
                        output(Map.of("id",id,"ok",false,"error",error instanceof IllegalArgumentException ? "invalid_credentials" : error instanceof TimeoutException ? "timeout" : "engine_failed"));
                    }
                });
            }
        }
        System.exit(0);
    }
}
