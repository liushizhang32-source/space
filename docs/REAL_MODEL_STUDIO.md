# 纸书智伴本地真实模型工作室

本入口实现无需手动处理模型中间产物的整本绘本流程。原离线V1接口、原成员四前端、原M1/M2冻结文件均保留；工作室使用独立页面和 `/studio` 路由，默认仅监听127.0.0.1:8765。真实云端调用须由用户填Key、核实账户权限/价格并确认费用。离线验收里的云端响应是明确Mock，不是实际Wan/CosyVoice效果。

## 安装与启动（Windows / PowerShell）

在仓库根目录运行：

```powershell
./scripts/install_all.ps1
./scripts/start_system.ps1
```

安装器创建 `.runtime/app` 和 `.runtime/ocr` 两个Python3.12环境，安装原生依赖、校验媒体工具/字体、预热并核验轻量OCR。优先复用已安装Python；缺失时下载官方签名的Python3.12安装器。支持 `-PythonPath` 显式指定。代码不依赖其他成员开发机的未提交文件，所有工具路径均由安装器写入被Git忽略的 `.runtime/tools.json`。

进入 [本地工作室](http://127.0.0.1:8765)：

1. 第一区“连接你的模型”输入百炼北京地域Key，保存；也可启动前设置 `DASHSCOPE_API_KEY`。页面密码框会清空，Key仅保存在后端内存，重启重新输入。
2. “检查连接”只查询认证/型号目录，不调用收费推理，也不宣称各模型权限通过。请在账户控制台确认模型权限与当前价格。
3. 第二区上传 JPG/JPEG/PNG/PDF 或多张图片，查看预览、调整顺序、填写书名和年龄。每文件20MB，整本最多30页。预览与OCR本地进行。
4. 估算费用，核实单次上限及全项目剩余预算，勾选云端素材/费用和账户权限确认，再生成。全书超过预算时可减少每页分镜上限（配置1—4），重新报价。不会自动购买服务或提高预算。
5. 第三区查看OCR/VLM/故事/分镜/语音/视频/合成进度，完成后播放或下载MP4、MP3与SRT，查看故事和分镜。字幕由真实语音片段时长定位，按句时间区间，不声称逐字强制对齐。
6. 第四区根据当前绘本和页面提问。文字或≤60秒录音经独立费用同意后调用Agent及同音色语音回复；ASR用同Key的Qwen3-ASR，Qwen-Plus不直接接受录音。搜索默认关闭。

该任务的用户目标年龄3—8岁映射到未修改的C3年龄枚举 `3-6` / `6-9`，没有私改冻结Schema添加新枚举。上传之后、开始Attempt之前可排序；开始后输入不可变，修改绘本请重新上传并批准新报价。

## 授权、费用与恢复

唯一原Authority位于 `%LOCALAPPDATA%/PaperbookZhiban/m1-local-cloud`，跨代码目录、模型和任务共享15000分预算。没有重置按钮，也不删除未知账务。测试使用隔离的显式临时实例，不影响该账户。

原M1 `begin/submit/cancel`负责资金规则；工作流元数据同库受原锚保护。第一个收费请求前才把保留状态置为UNKNOWN并持久记录提交。只在确认未提交的RESERVED状态使用原cancel释放；HTTP失败/超时/取消后不自动退款。实际费用未知时显示“待对账”，不得把token usage/估算或签名fixture账单写入真实结算。

Key不保存到磁盘，关停后需重输。“历史任务 / 断点恢复”能恢复已有Wan Task ID、结果和授权身份；不重复提交不确定的收费POST。已丢失响应且没有Task ID的收费请求保持UNKNOWN并拒绝重发，需M1/账户管理员核对。成功结果URL通常24小时有效，过期不偷偷重新收费生成。

API Key本身未提供已审核的可信人民币账单入口，因此本版本不开放真实结算HTTP。M1负责人接入可信官方账单适配器前保持UNKNOWN；原fixture结算器和fixture证明已禁止用于dashscope Attempt。此限制不妨碍在确认上限内做首次真实模型测试，但会占用保留预算。

“取消任务”停止后续调用、撤销访问，并等待当前HTTP请求/原生进程树结束。Wan远端只能取消PENDING，RUNNING不得假称已退款。本地原生工具复用M1 WindowsTree，先加入Job Object再执行，取消时等待完整进程树；无法证明退出时保留隔离文件。产物没有静态目录、FileResponse或StreamingResponse旁路，Range也从M1授权后的同一份字节切片。

```powershell
./scripts/check_environment.ps1
./scripts/check_model_connections.ps1
./scripts/run_all_tests.ps1
./scripts/stop_system.ps1
```

命令行全链路同样必须明确授权，未给同意开关时只上传和报价：

```powershell
./scripts/run_full_pipeline.ps1 -Files page1.jpg,page2.jpg -Title '森林里的朋友' -Age 3-6
# 仅在已保存Key、核实账户权限和价格，并接受本次实际费用后：
./scripts/run_full_pipeline.ps1 -Files page1.jpg,page2.jpg -CostLimit 15 -ApproveCloudAndCost -AccountPermissionsConfirmed
```

## 成员四接入与接口边界

没有覆盖成员四分支及既有A4/A5协议。现有主应用仍使用其原工厂/原路由/原离线测试；新入口不是把旧Mock模式偷改成生产模式。成员四可在保留旧API的前提下接入以下本机同源接口：

|接口|输入 / 输出|
|---|---|
|GET /studio/session|建立HttpOnly会话，返回CSRF；后续写请求带X-CSRF-Token|
|GET/POST /studio/config|只回非秘密配置及api_key_present；POST的api_key仅后端内存|
|POST /studio/connections|不计费认证/目录检查，权限UNVERIFIED|
|POST /studio/books|multipart files；图片/PDF→带ID、SHA的页列表|
|POST /studio/books/{id}/order|page_ids完整排列；返回新输入revision|
|POST /studio/books/{id}/quote|title、age；报价绑定输入与配置，15分钟到期|
|POST /studio/generate|quote_id、cap_fen、cloud_consent、account_permissions_confirmed、request_id|
|GET /studio/jobs/{id}|状态、stage、progress、准确身份、结果、UNKNOWN费用；GET只读业务状态|
|POST /studio/jobs/{id}/cancel、resume|撤销/明确恢复原任务，UNKNOWN不自动重交|
|GET /studio/assets/{opaque server-generated name}|会话及原M1授权，Content-Type/SHA/Range一致，不接受本地绝对路径|
|POST /studio/questions|job_id、page_no、question、cap_fen、consent、request_id；答复及受权音频URL|
|POST /studio/questions/audio|multipart audio + JSON request同上；真实解码→ASR→Agent→CosyVoice|

跨端口的成员四页面应由其服务端BFF代理并保留用户会话和CSRF，不能把M1服务凭据或百炼Key交给浏览器，不能把私有视频URL改成无认证静态链接。接口扩展见P5；不伪造ASR置信度以硬套旧示例，旧A4/A5的正式字段演进仍由成员四和M1负责人签认。

## 验证范围

新增测试包含真实Paddle中文识别、原生OpenCV、真实FFmpeg完整音视频及字幕、多页/PDF、真实浏览器HTTP、预算、Key、CSRF、M1撤销/续期、取消与断点恢复。云端统一用显式MockTransport注入，无生产环境开关可启用Mock；验收网络守卫拒绝非本机Python网络。原M1/M2/M3与九组CI全部继续执行，各集合重叠不相加。

验收器要求源码已提交且干净，保存tested_commit及测试前后所有源文件SHA，不把其他分支/旧测试当当前提交证据。音频sine与动态testsrc仅用于明确的测试夹具。真实模型质量、Wan动作/角色一致性、CosyVoice听感仍须Key后单页、多页实测，不能由离线测试签认。

字体来自Noto CJK的固定官方提交，沿用原 `prepare_ci_font.py` SHA校验及其许可证；FFmpeg动态安装，遵守上游GPL许可；OCR权重不进入Git。没有生产部署、分支保护修改、main强推或自动合并。
