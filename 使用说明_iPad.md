# 纸书智伴 iPad 完整应用

电脑运行后端，iPad Safari/PWA运行界面。PaddleOCR/OpenCV/FFmpeg在电脑上；Qwen-VL、Qwen故事/Agent、CosyVoice3、Wan使用同一个北京百炼Key。全项目预算150元，沿用原M1账本；UNKNOWN不伪造结算或自动释放。

## 解压、安装、启动

1. 将完整目录解压至Windows电脑可写目录。双击 **INSTALL.bat**，联网安装两个隔离Python环境、轻量OCR权重、媒体工具、中文字体和WebKit测试浏览器。无需下载本地Qwen/Wan/CosyVoice。
2. 双击 **START_IPAD_SERVER.bat**，在Windows UAC提示中批准本次管理员操作。仅为应用8766/8767端口创建“当前私有IPv4 + LocalSubnet + 此Python程序”的入站规则；不关闭防火墙、不改变Wi-Fi公共/专用分类、不做端口转发。
3. 终端首次显示家长口令，请妥善保存。自动打开“iPad连接”页面，其中有电脑/iPad地址、二维码、家庭CA指纹和五分钟一次性配对码。iPad和电脑连接同一Wi-Fi。
4. iPad扫码进入公开证书安装引导（HTTP仅提供公开CA，无业务数据）。与电脑对照SHA256指纹，下载家庭CA证书，按系统提示安装描述文件。随后在 **设置→通用→关于本机→证书信任设置** 手动启用此CA完全信任。电脑脚本只信任当前Windows用户的该家庭CA，不能代替iPad上的手动信任。
5. 打开引导页的HTTPS链接，再输入电脑上的一次性配对码。家长也可在电脑HTTPS页面登录家长中心重新生成配对码、查看或撤销设备。
6. Safari“分享→添加到主屏幕”可安装PWA。支持横竖屏和触控；PWA只缓存公开界面，不缓存绘本、视频、API响应、API Key或设备凭据。离线只能看已缓存界面，业务操作需要电脑在线。

**CHECK_SYSTEM.bat**：检查原生OCR/媒体环境及后端状态。**STOP_SERVER.bat**：输入家长口令后优雅停止，等待正在执行的原生进程树结束，不强制退款。网络IP改变后重新启动并使用新二维码；CA保持，服务证书重新签发。旧防火墙规则的IP需要由启动脚本更新，不能沿用失效地址。

## 儿童操作

- 产品首页、书架、上传、AI工坊、播放器、点读及问答为独立页面；Key和费用管理只在家长中心，服务端也会拒绝儿童设备直接调用管理/收费接口。
- 拍照支持后置摄像头；相册支持JPEG/PNG/HEIC/HEIF；支持多图片、PDF、排序与预览。每文件20MB，整本30页；配对授权后可在无Key时上传并运行真实本地OCR。
- 点读：先运行OCR，再在播放器页点文字区域，以设备本地语音朗读；它不是CosyVoice，界面明确标注。识别坐标使用与预览一致的规范化页面。
- 真实生成由家长选择书名、年龄、估算费用、核实账户模型权限/价格，确认本次上限与素材云端传输后启动。原M1统一保留预算和授权，未获账单时费用保持待对账。
- 播放器支持H.264 + AAC MP4、playsinline、用户点击播放、Safari原生全屏、下载；直接媒体请求失败时可经同源授权获取Blob后播放，最大单资产64MB，不公开文件目录。
- 语音问答仅在点击后申请麦克风；优先Safari audio/mp4，回退WebM。拒绝权限/非安全上下文时使用文字输入。家长需要先按设备ID和已完成任务ID批准一次问答额度（5分钟有效），儿童界面没有金额输入。按真实ASR→Agent→CosyVoice调用，录音最长60秒。页面隐藏时停止录音，清理麦克风轨道。
- 无Key演示按钮明确标记 **MOCK**：示例绘本、本地绘制动态视频、测试音和固定问答，不代表Wan、CosyVoice或真实模型质量。可以播放已有受权产物，不能把演示显示成真实生成成功。

## 家长与凭据

家长口令哈希存储；按用户选择，家长会话长期保持并跨后端重启恢复，主动锁定、清除浏览器Cookie或重设口令后失效。只持久化会话令牌的SHA256引用，不保存原始Cookie；提供锁定按钮；设备配对码一次性、5分钟到期并限速。会话Cookie为Secure/HttpOnly/SameSite=Strict，写入需CSRF，校验Origin/Host与局域网来源。API Key只在电脑后端内存或DASHSCOPE_API_KEY环境变量中，不在前端/PWA缓存/源码/日志/交付包里，重启后重新输入。

家长在配置区输入Key并安全保存，再进行不计费认证检查；型号目录不代表模型权限。必须在百炼账户确认权限与费用，真实生成才能开始。本地M1签名和家庭CA不是生产KMS，P1—P5仍为PROPOSED，未开启生产部署或自动合并。

Windows用户可用`.runtime/app/Scripts/python.exe scripts/ipad_control.py reset-pin`在本机重设家长口令；不能从儿童API重置。家庭CA及设备信息保留在LocalAppData/PaperbookZhiban/m1-local-cloud/ipad-security，不能把含私钥的目录发给别人。每次新电脑安装生成自己的CA，不共享开发机证书。

## iPad一直载入的排查

- 必须输入完整端口：首次引导`http://电脑IP:8767/`，应用`https://电脑IP:8766/`，只输入电脑IP会访问错误的80端口。
- 电脑与iPad须同一Wi-Fi且未启用访客/AP客户端隔离。核对iPad详情中的“IP地址”，不要把“路由器”地址当iPad地址。
- Windows虚拟环境入口会转到实际底层Python。启动器按`sys._base_executable`配置防火墙程序路径，并在重复启动时修复规则；只放行指定私有IPv4、本地子网、8766/8767两端口。
- 如果服务由Codex/其他隔离运行环境启动，隔离环境可能额外禁止非回环入站。不要修改或关闭隔离规则；安全停止该实例后，由设备持有人在正常Windows资源管理器中双击START_IPAD_SERVER.bat启动。
- 防火墙规则添加与修复需Windows UAC批准。引导页都打不开时先查网络/防火墙；能打开引导页但HTTPS失败时再按引导安装并信任家庭CA。

## 验收范围

`tests/ipad`覆盖授权/撤销、家长与儿童边界、CSRF/Origin、HEIC/PDF、多页、PWA静态缓存限制、严格证书链/SAN、四种iPad横竖视口及真实视频播放。Windows WebKit与Safari的媒体编解码器不同，因此保留Windows失败证据，同时使用macOS WebKit执行相同完整播放断言，不把真机或云端测试写成通过。原96项真实本地/模拟云端验收与原M1/M2/M3完整回归继续保留。

当前机器的局域网地址由启动器自动检测，不能硬编码给其他电脑。Windows防火墙/UAC未获管理员确认时，必须报告未完成局域网放行；同机LAN地址访问不等于真实iPad跨设备验证。真机PWA安装、iPad证书信任、麦克风/摄像头与真实云效果都需设备持有人后续确认。

官方依据：[Apple手动证书信任](https://support.apple.com/en-ie/102390)；[Playwright说明WebKit与操作系统编解码器差异](https://github.com/microsoft/playwright/blob/main/docs/src/browsers.md)。模型与价格沿用docs/OFFICIAL_MODEL_CATALOG.md。
