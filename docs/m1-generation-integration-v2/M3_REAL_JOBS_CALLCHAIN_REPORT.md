任务 M1-M3-IMPLEMENTATION-001；2026-11-16，Asia/Hong_Kong。

状态：CI_ONLY / M1_SIGNOFF_PENDING / ARCHITECTURE_DECISION_REQUIRED。

# 实际调用链

CI_ONLY 的真实路径已经执行：

```text
POST /api/v1/generate
  -> Member3Jobs.create/run/_run
  -> Member3Session.step(story)
  -> 受控 M1 Session factory(page_id, job_id, request_id=job_id:page_id)
  -> M1 open_session(既有 Consumer、Gate、Authority、SharedFences)
  -> B.run_page(m1=session, make_video=False, cancelled=flag.is_set)
     -> 授权输入 -> Story Builder -> 每段 TTS 一次
     -> 最终 story.json 原始 bytes -> submit_story_bytes
  -> Adapter 校验已提交 hash、Story schema/safety
  -> tts stage 只做已有音频深度/URL/时长检查，不再生成或写 Story
  -> render stage 复用原 compose_video/深度验证/恢复逻辑
  -> 取消检查 -> 发布前全部 hash 校验 -> 临时副本 hash -> os.replace
  -> 内部回执/审计 JSONL/UNKNOWN 对账入口 -> close
```

只按阶段调度，不复制 Pipeline 业务。原 Adapter builder 分支在授权模式不可达；实际 spy 断言 B.run_page 一次、Builder 一次、TTS 调用数等于 Story segments。音视频、Story 与临时副本均校验；提交后不调用 save_story。测试读取最终公开 Story 文件，SHA256 等于 M1 返回的 result_sha256。

原 jobs 的 executor Future、shield drain、重复 cancel、force 替换与 shutdown 路径保留。授权任务取消时先等待 worker drain；如果取消发生在提交前，B 释放 RESERVED 且不提交；提交开始后取消只阻止发布，不自动 cancel 预算。force 测试验证旧任务不能发布；替换任务的 M1 上游换代/再次准入由 M1 provider 决定，未绕过未决 attempt。

create_app 只有进程内 keyword-only m1_session_factory 注入；默认 None 继续本地非 M1 模式。没有新增公共 API、修改公共 Schema、自动生产装配或激活 DRAFT。正式 M1 provider 因签认阻塞未交付；REAL_JOBS_CALLCHAIN_PASS 仅指 CI_ONLY 原版 M1 fixture 条件下真实 HTTP/Jobs 链，不是 production readiness。

新增 12 项测试覆盖：真实 B 调用/单次生成/发布 hash；视频 blocked；释放错误审计；submit 响应丢失 UNKNOWN；提交前 cancel 与 force（2 项）；提交后篡改拒绝发布；None 本地模式；回执字段；TTS 降级字节；提交后取消；B 直接视频 blocked。加上31项原 Adapter/生命周期测试，全部通过，原断言未降低。
