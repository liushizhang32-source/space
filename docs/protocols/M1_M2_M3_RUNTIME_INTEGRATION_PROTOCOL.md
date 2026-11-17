# P3 三模块运行时

Version: 1.0
Status: PROPOSED
Date: 2026-11-17 (Asia/Hong_Kong)

本轮用户授权设计和离线实现；等待ChatGPT独立审核后冻结。冻结公共API和M1/M2 V1.0优先。本文件不是生产许可。

## P3-01 HTTP请求

原capture/generate/jobs/A6字段和公开C1/C2保持冻结；新私有读取是独立显式profile，不改旧响应字段。

## P3-02 响应/错误

公开JSON保持code,msg,data,trace_id；业务HTTP200和M1静态blocked503保持；私有二进制profile用200/403，拒绝JSON用原1005，不新增公开错误码。

## P3-03 Job

queued→running→done/partial_failed/failed/cancelled沿用原实现；Page blocked不新增Job blocked；媒体no_audio/no_video原降级保持。

## P3-04 Session

M1受控factory，M3不签Token；原Bridge先验Gate/current/image/hash，再原Authority.begin；会话失败只按原状态释放。

## P3-05 Gate

源注册由M1配置，不信worker声明；原C1/C2/refs严格类型、字节hash、identity、fencing及安全证据校验不变。

## P3-06 M2 Worker

真实CLI每进程一次stage；m1-vision-worker/0.1和vision_refs/0.1不增加字段；显式fixture/stub不等于真实模型。

## P3-07 Generation

原唯一B Pipeline；已提交Story bytes不可改写；每页builder一次、每段TTS一次；原预算Attempt与业务Job分层。

## P3-08 TTS

主和独立工厂复用M1策略；POST缓存读取前拒绝；P2提供私有输出正向读取，旧local demo只是隔离演示。

## P3-09 Video

真实ffmpeg解码/元数据/hash验收；普通视频失败按no_video降级，安全3004无最终输出；媒体发布需当前fences。

## P3-10 取消

typed取消不重试；M1终止真实树、wait/reap后报告；上游撤销阻止旧发布和读取；已提交UNKNOWN不能强转取消释放。

## P3-11 超时

deadline≤30秒，M1监管而非客户端超时断言；不明后端终态保持UNKNOWN/隔离。

## P3-12 重试

冻结F08的每逻辑stage跨重启总2次，精确2001/2002/2003+transient+终止确认+live+1秒退避；2004未批准子类型集合为空。

## P3-13 幂等

活动HTTP请求原job幂等；stage dispatch原持久唯一；提交同SHA幂等；P1事件和receipt幂等，P2登记不可变。

## P3-14 恢复

复用Authority/SharedFences/原快照，P1持久inbox重放，不把JSONL生成视作恢复完成；不重投未决。恢复的同路径原子replace仅对Windows临时共享错误5/32/33重试至1秒；持久拒绝仍抛错并保留maintenance/隔离，不删除数据或跳过安全校验。

## P3-15 Trace

公开trace_id原规则；内部审计以真实job/page/Attempt和事件ID关联，不把trace当授权。

## P3-16 Attempt

原七元identity由M1产生；OCR/VLM attempt/token分离且五元相同；Generation原lineage不可替换。

## P3-17 Asset Reference

P2 asset_id→不可变project/job/Attempt/SHA/路径映射；URL非授权，凭证不在URL。

## P3-18 版本

冻结M1/M2 V1.0优先于本PROPOSED v1.0；未知新字段拒绝；不对公开Pydantic模型擅加extra=forbid。

## P3-19 环境

离线适配、fixture、安全测试密钥、silent TTS明确记录；真实OCR/Qwen/供应商账单/生产认证均外部独立验收。

## P3-20 测试向量

P3-V01原255/261/242；V02真实CLI5/多页/失败7；V03原UNKNOWN；V04联合生成→P2私有读取→P1可信离线结算。
