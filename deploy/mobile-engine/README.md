# 手机会话引擎

使用 Maven Central 已发布的 `com.github.auties00:cobalt:0.0.10`，Java 21 及以上。
这是独立的手机协议客户端；不修改现有 Baileys 扫码引擎。

构建并安装：

```bash
mvn -f deploy/mobile-engine/pom.xml package
cp deploy/mobile-engine/target/mobile-engine-1.0.0.jar deploy/mobile-engine/mobile-engine.jar
```

后端按需启动一个 JVM，通过标准输入/输出传递命令，不开放网络监听端口。
可通过 `WA_MOBILE_JAVA` 指定 Java 可执行文件、`WA_MOBILE_ENGINE_JAR` 指定 JAR。
会话保存到 `WHATSAPP_AUTH_ROOT/whatsapp_auth/mobile/t租户-a账号`，顶层目录权限为 700。
不要提交 JAR、登录会话或账号凭据。备份必须覆盖数据库与会话目录。

六段顺序是号码、Noise 公钥、Noise 私钥、Signal 身份公钥、Signal 身份私钥、身份标识。
六段文件没有设备版本，采用 SDK 的 iOS 手机配置并获取版本；需要固定版本时可设置
`WA_MOBILE_SIX_VERSION`。全参格式保留提供的 Android 设备型号、OS 版本、App 版本、
身份密钥、静态密钥、签名预密钥和注册编号。全参没有提供 SDK registration-only 的
identityId 时，使用 deviceUUID 字节作为本地字段；不会发起重新注册或获取验证码。

账号操作提供手机协议登录、断开连接。只有服务器登录事件确认正确号码后才显示在线。
开始养号后每分钟执行在线状态保活，成功检查之间的在线时间最多每次计入 120 秒。
中断、失败和服务停机时间不计入。失败退避重试，连续三次失败停止恢复并暂停养号。
暂停会断开连接；恢复需要先重新登录。不会发送消息、上传联系人或自动提高健康分。

验证：

```bash
python tests/mobile_engine_test.py
python tests/mobile_maintenance_test.py
python tests/workspace_test.py
```

引擎测试使用离线合成凭据验证字段映射、持久化和租户隔离，不能证明真实账号已登录。
上线后仍须以账号列表的服务器确认状态和保活记录判断结果。

上游来源：[Cobalt](https://github.com/Auties00/Cobalt)，MIT 许可证。
本服务只使用文本与连接功能，不包含 Aspose 文档转换依赖。
