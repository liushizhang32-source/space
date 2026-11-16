# VLM 执行边界与取消语义（V1.2.1 P0-2）

> 结论先说：M2 能证明的是“**Worker 进程树被终止并回收**”，不能证明
> “**远端/常驻模型服务上的那次计算已经停止**”。后者只能由模型服务的取消接口
> 或 M1 的 OS 级容器（Job Object / cgroup）来证明。本文件把边界、已做的实现、
> 实测数据和需要 M1 决定的部分分开写清楚。

## 1. 问题

V1.2 的实现是“Worker 进程内用 HTTP 调一个常驻 VLM 服务（本机 Ollama）”：

```text
M1 Supervisor ──拉起──> m2_vision_worker.py ──HTTP──> ollama serve (常驻)
```

杀掉 Worker 只能终止**客户端**。`ollama serve` 里那次 forward 仍在跑，
直到它自己算完。因此“终止 Worker 客户端”不能当作“模型计算已终止”的证据。
独立审查 P0-2 指的就是这一点。

## 2. 三层可验证性

| 层 | 能否由 M2 证明 | 手段 |
|---|---|---|
| Worker 进程本身退出 | ✅ | 进程退出码 + `result.json` |
| Worker 派生的子进程/孙进程全部消失 | ✅（`subprocess` 模式） | `taskkill /T` / 进程组 kill + `wait` |
| 模型服务端那次计算停止 | ❌（M2 单方面） | 需要服务端 cancel API 或 OS 容器 |

## 3. M2 已实现的两种执行模式

### 3.1 `M2_VLM_EXEC=inproc`（默认）

- 在 Worker 进程内直接调后端；进程退出即客户端消失。
- 优点：少一次进程启动，延迟低（本机实测 VLM 约 10.6 s）。
- 缺点：M1 硬墙杀树时，模型端仍在算（见第 1 节）。

### 3.2 `M2_VLM_EXEC=subprocess`

- Worker 在 attempt 目录下建 `tempfile.mkdtemp(prefix=".m2vlm_")`，
  写 `input.bin` + `job.json`，用 `sys.executable -m vision.vlm_child` 起子进程。
- 子进程自己加载图片、调后端、把结果写到 `out.json`；父进程只做编排。
- 超时/失败时：`taskkill /F /T /PID`（Windows，整棵树）+ `proc.kill()`，
  再 `communicate()` 回收管道与僵尸句柄，最后删临时目录。
- **这一步让“模型客户端”落在 M1 的进程树里**：M1 用 Job Object 杀树时，
  能连带杀掉这个子进程，而不是只杀 Worker。

## 4. 实测数据（本机 Windows 10.0.26200）

| 项 | 值 | 证据 |
|---|---|---|
| 子进程被杀 + 回收耗时 | 1.045 s / 1.038 s / 1.043 s（3 次） | 本次 `_run_child(sleep 30, timeout=1)` 测量 |
| 真实 OCR 单页 | 8.3 s（1000×1414，3 块，conf 0.9925） | `docs/logs/worker_smoke_ocr_real.log` |
| 真实 VLM 单页 | 10.6 s（C2 ok，1 物体，safety=true） | `docs/logs/worker_smoke_vlm_real.log` |
| 超时用例 | `test_child_process_timeout_is_killed_and_reaped` 通过（<15 s 断言） | `tests/test_worker_v121.py` |

“1 秒级回收”说明**客户端侧**的终止是确定性的；它不覆盖服务端计算。

## 5. 要证明“模型计算已停止”，需要什么

按可落地程度排序，三条路：

1. **服务端取消接口**（最干净）：vLLM/Ollama 提供 request abort 时，Worker 在
   `finally` 里发取消请求，并等一个服务端确认。当前 Ollama 版本没有稳定的
   取消语义，所以 M2 不宣称支持。
2. **每次 attempt 一个模型进程/容器**（可验证）：M1 用 cgroup v2 / Job Object
   把“模型服务 + Worker”放进同一个可杀容器；`cgroup.kill` 或
   `TerminateJobObject` 之后确认 `active=0`，就能证明计算停止。这正是 M1 报告里
   Windows Job Object 的做法——只要模型进程也被放进去。
3. **接受浪费、只约束资源**：承认被杀的那次 forward 会跑完，但用容器配额
   （CPU/内存/并发=1）保证不会累积。这条最容易，但“取消”只是逻辑上的。

M2 的建议：短期用 1 + 2 的组合（M1 的 attempt 容器里同时放模型进程；
Worker 侧 `subprocess` 模式保证客户端在同一棵树里），中期推动模型服务提供
取消接口。M2 不在本轮自行实现“第二套进程监管”。

## 6. 本轮交付的边界声明

- M2 负责：单次 OCR/VLM Worker、子进程执行模式、超时后杀**自己派生的**进程树并回收。
- M1 负责：30 秒硬墙、整棵 attempt 树的终止与 `wait`、确认 `active=0`。
- **未执行**：真实 Ollama 在 kill 后是否停止计算的观测（需要服务端指标），
  以及 Linux cgroup 路径。这两项在 `docs/M1_INTEGRATION_REPORT.md` 的
  “未执行”清单里，不做任何“已验证”的表述。
