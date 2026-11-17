# P2 M1/M3私有资产授权

Version: 1.0
Status: PROPOSED
Date: 2026-11-17 (Asia/Hong_Kong)

本轮用户授权设计和离线实现；等待ChatGPT独立审核后冻结。冻结公共API和M1/M2 V1.0优先。本文件不是生产许可。

## P2-01 单一权威

PrivateAssets是原M1 Authority的输出资产适配层，共用原SQLite、签名令牌、grants、key revocation和clock；M2/M3不能自建权限表或签发服务。

## P2-02 身份验证

Authorization: Bearer携带原M1 service token；X-M1-Asset-Token携带原M1签发的asset_access token；两者由原_token校验签名/持久记录/有效期/密钥撤销。仅Header名称无授权意义。

## P2-03 正向条件

两token有效且同subject；service对同project有assets.read；asset_id、项目、job、attempt、版本SHA与服务端登记一致；任务/资产未撤销；上游current/fences仍有效；读取前后全部复核，才释放bytes。

## P2-04 输出登记

仅M1受控发布者register_output；已提交SUBMITTED/UNKNOWN或已结算DONE的原Attempt/ResultSHA、当前页代际与服务授权匹配。输出路径只能是audios/*.mp3、videos/*_video.mp4、json/*_story.json，不公开C1/C2/refs/manifest/internal文件。

## P2-05 Asset ID

字母开头小写字母数字下划线短横线，≤64；HTTP只传Asset ID不传路径；登记是不可变映射，不允许相同ID重绑不同内容。

## P2-06 项目/任务

元数据来自原attempt.project、identity.job_id/page_id，不信客户端自报；读取参数与服务端project/job和token绑定同时一致。

## P2-07 范围/有效期

asset_access令牌只包含一个登记asset的SHA及原attempt；复用assets.read，ttl原生int 1..300秒；默认60秒；禁止URL bearer与日志token。

## P2-08 撤销

原service/access/key/grant撤销即时在读取前后检查；M1 revoke_task撤销该项目job的所有输出，并阻止重新登记；上游Fences撤销也拒绝。已释放的响应不承诺追溯追回，二次授权事务为线性化点。

## P2-09 路径

复用safe_name和WindowsAssetReader；拒绝百分号、冒号、反斜杠、绝对路径、空/..组件、设备名、UNC/非NTFS，不用resolve字符串冒充OS保证。

## P2-10 符号链接/逃逸

原生固定根句柄、逐层无reparse、同句柄读取、hardlink数=1和禁止并发写/删；不支持OS直接拒绝。符号链接测试无权限时明确SKIPPED，不伪称已测。

## P2-11 先授权再读取

读前完整事务授权通过后才调用WindowsAssetReader；读后校验输出SHA并再次事务授权；拒绝前不得打开目标，篡改或撤销后不返回已读bytes。

## P2-12 静态访问

主应用和独立TTS旧/audios等继续原M1 blocked/显式demo规则，不把私有目录挂裸StaticFiles。私有资源只从显式注入的同一M1适配器挂载/_m1/assets/{asset_id}读取。

## P2-13 TTS和Video

二者走同一M1输出登记/读取；返回已授权内存Response，不在授权后用FileResponse/StreamingResponse重新打开文件；先缓冲后终验。

## P2-14 内部读取

内部消费者调用同一read方法，不得绕过；原视觉AuthorizedAssetReader仍适用其视觉快照合同，不改造成第二套TTS权限。

## P2-15 HTTP

新私有profile成功200+登记Content-Type，Cache-Control:no-store；拒绝403+现有code1005/msg/data:null/trace_id，不暴露路径/存在性/私有字节；旧公开HTTP契约不改。

## P2-16 审计

Authority事件记录subject/project/job/asset及摘要，拒绝记录安全原因；不记录凭证/原文件bytes。

## P2-17 隔离与激活

仅显式offline_test/local且配置注入才有新路由；默认无适配器不提供私有读取；不启用生产身份/KMS，正向身份来自离线测试Authority。

## P2-18 测试向量

P2-V01合法音频/视频；V02缺凭证/跨项目/错job/过期；V03任务/令牌/密钥/上游撤销；V04路径/硬链接/reparse；V05读取中撤销/内容篡改；V06主/独立TTS同实例响应bytes。

## P2-19 责任

M1维护原Authority及本适配；M3负责接线/输出；M2只产视觉候选。生产接入必须独立审核此PROPOSED协议。
