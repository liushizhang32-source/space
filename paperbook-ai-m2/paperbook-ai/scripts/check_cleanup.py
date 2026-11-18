"""故障注入：验证 isolated_check.py 的临时目录清理是否可靠。

    python scripts/check_cleanup.py

十二个场景：
1. 创建目录后立即发生异常
2. 初始化阶段发生异常
3. 测试执行阶段发生异常
4. 连续三次异常（不得新增残留）
5. 清理操作自身失败（必须留日志）
6. 原始异常与清理异常同时发生（原始异常优先）
7. 已存在其他测试目录时执行清理（不得误删）
8. 实现中不出现 ignore_errors（静态检查）
9. 预置固定同名目录（_isolated_0000dead）时不得覆盖或删除
10. 报告抛出异常时不得顶替原始业务异常
11. 只有报告失败（无原异常）时返回 1
12. 连续三次打印异常（stdout 损坏）不得累积目录

退出码：0 全部通过；1 有失败项。
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts" / "isolated_check.py"
RESULTS: list[tuple[str, bool, str]] = []


def _load():
    spec = importlib.util.spec_from_file_location("isolated_check_under_test", TARGET)
    assert spec and spec.loader, TARGET
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dirs() -> set[str]:
    root = ROOT / "data"
    if not root.exists():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir() and p.name.startswith("_isolated_")}


def _call(module, *, target: str | None = None, exc: BaseException | None = None,
          rmtree_exc: BaseException | None = None,
          report_exc: BaseException | None = None,
          print_exc: BaseException | None = None):
    """跑一次 main()，返回 (退出码或异常, stdout, stderr, 新目录集合)。"""
    module.RESULTS.clear()
    out, err = io.StringIO(), io.StringIO()
    raised: BaseException | None = None
    code: int | None = None

    patchers = []
    if target is not None:
        patchers.append(mock.patch.object(module, target, side_effect=exc))
    if rmtree_exc is not None:
        patchers.append(mock.patch.object(shutil, "rmtree", side_effect=rmtree_exc))
    if report_exc is not None:
        patchers.append(mock.patch.object(module, "_report", side_effect=report_exc))
    if print_exc is not None:
        patchers.append(mock.patch("builtins.print", side_effect=print_exc))

    try:
        for patcher in patchers:
            patcher.start()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = module.main([])
        except BaseException as error:  # noqa: BLE001 - 故障注入就是要接住它
            raised = error
    finally:
        for patcher in reversed(patchers):
            patcher.stop()

    return (raised if raised is not None else code), out.getvalue(), err.getvalue(), _dirs()


def scenario(name, fn) -> None:
    try:
        detail = fn() or ""
        RESULTS.append((name, True, detail))
    except AssertionError as error:
        RESULTS.append((name, False, str(error)[:200]))
    except Exception as error:  # noqa: BLE001
        RESULTS.append((name, False, f"{type(error).__name__}: {error}"[:200]))


def _no_new(before: set[str], after: set[str], where: str) -> None:
    added = after - before
    assert not added, f"{where} 新增残留目录：{sorted(added)}"


def main() -> int:
    module = _load()

    def s1():
        before = _dirs()
        result, _, err, after = _call(module, target="_make_workdirs",
                                      exc=RuntimeError("注入：创建目录后立即异常"))
        assert isinstance(result, RuntimeError), f"原始异常未保留：{result!r}"
        _no_new(before, after, "场景1")
        return "异常向上传播，临时目录已清理"

    def s2():
        before = _dirs()
        result, _, _, after = _call(module, target="_preflight",
                                    exc=RuntimeError("注入：初始化阶段异常"))
        assert isinstance(result, RuntimeError), f"原始异常未保留：{result!r}"
        _no_new(before, after, "场景2")
        return "初始化失败后仍执行清理"

    def s3():
        before = _dirs()
        result, _, _, after = _call(module, target="run",
                                    exc=RuntimeError("注入：测试执行阶段异常"))
        assert isinstance(result, RuntimeError), f"原始异常未保留：{result!r}"
        _no_new(before, after, "场景3")
        return "测试中途异常后仍执行清理"

    def s4():
        before = _dirs()
        for index in range(3):
            result, _, _, after = _call(module, target="run",
                                        exc=RuntimeError(f"注入：第{index + 1}次异常"))
            assert isinstance(result, RuntimeError), f"第{index + 1}次异常未保留：{result!r}"
            _no_new(before, after, f"场景4 第{index + 1}次")
        after = _dirs()
        assert after == before, f"三次异常后残留：{sorted(after - before)}"
        return f"连续 3 次异常，残留数保持 {len(before)}"

    def s5():
        before = _dirs()
        module.CLEANUP_LOG.unlink(missing_ok=True)
        code, _, err, after = _call(module, rmtree_exc=OSError("注入：清理自身失败"))
        assert code == 2, f"清理失败应返回 2，实际 {code!r}"
        assert "CLEANUP-FAIL" in err, "stderr 没有清理失败日志"
        assert module.CLEANUP_LOG.exists(), "没有落盘清理日志"
        text = module.CLEANUP_LOG.read_text(encoding="utf-8")
        assert "注入：清理自身失败" in text, text[:200]
        leftover = after - before
        assert len(leftover) == 1, f"预期留下 1 个（清理失败无法删除），实际 {sorted(leftover)}"
        for name in leftover:  # 人工收尾，避免污染后续场景
            shutil.rmtree(ROOT / "data" / name, ignore_errors=False)
        return "返回 2 + 日志落盘，残留被记录后人工清除"

    def s6():
        before = _dirs()
        module.CLEANUP_LOG.unlink(missing_ok=True)
        result, _, err, after = _call(
            module, target="run", exc=ValueError("注入：业务异常"),
            rmtree_exc=OSError("注入：清理也失败"),
        )
        assert isinstance(result, ValueError), f"清理异常覆盖了原始异常：{result!r}"
        assert "CLEANUP-FAIL" in err, "清理失败未记录"
        leftover = after - before
        assert len(leftover) == 1, f"预期留下 1 个，实际 {sorted(leftover)}"
        for name in leftover:
            shutil.rmtree(ROOT / "data" / name, ignore_errors=False)
        return "抛出的仍是 ValueError，清理失败另有日志"

    def _fixture() -> Path:
        """独占创建一个测试用临时目录：名字随机，已存在就失败，绝不复用他人目录。"""
        path = ROOT / "data" / f"_isolated_{uuid.uuid4().hex[:8]}"
        path.mkdir(parents=False, exist_ok=False)
        (path / "keep.txt").write_text("别删我", encoding="utf-8")
        return path

    def s7():
        sibling = _fixture()
        try:
            now = _dirs()
            result, _, _, after = _call(module, target="run",
                                        exc=RuntimeError("注入：有其他目录时异常"))
            assert isinstance(result, RuntimeError), f"原始异常未保留：{result!r}"
            assert sibling.exists() and (sibling / "keep.txt").exists(), "误删了其他测试目录"
            _no_new(now, after, "场景7")
            return "他人的临时目录与文件完好"
        finally:
            shutil.rmtree(sibling)

    def s8():
        source = TARGET.read_text(encoding="utf-8")
        assert "ignore_errors" not in source, "发现 ignore_errors，违反要求 9"
        assert "CLEANUP-FAIL" in source and "REPORT-FAIL" in source
        return "未出现 ignore_errors"

    def s9():
        legacy = ROOT / "data" / "_isolated_0000dead"
        created_legacy = not legacy.exists()
        if created_legacy:
            legacy.mkdir(parents=True)
        marker = legacy / "REVIEWER PREEXISTING OWNER.txt"
        payload = "REVIEWER PREEXISTING OWNER"
        created_marker = not marker.exists()
        if created_marker:
            marker.write_text(payload, encoding="utf-8")
        try:
            before = _dirs()
            result, _, _, after = _call(module, target="run",
                                        exc=RuntimeError("注入：固定同名目录已存在"))
            assert isinstance(result, RuntimeError), f"原始异常未保留：{result!r}"
            assert legacy.exists(), "固定同名目录被删除"
            assert marker.read_text(encoding="utf-8") == payload, "固定同名目录内容被改写"
            _no_new(before, after, "场景9")
            return "预置同名目录与标记均未被触碰"
        finally:
            if created_marker:
                marker.unlink(missing_ok=True)
            if created_legacy:
                shutil.rmtree(legacy)

    def s10():
        before = _dirs()
        result, _, err, after = _call(
            module, target="run", exc=ValueError("MOCK original business failure"),
            report_exc=OSError("MOCK report failed"),
        )
        assert isinstance(result, ValueError), f"报告异常替换了原始异常：{result!r}"
        assert "MOCK original business failure" in str(result), str(result)
        assert "REPORT-FAIL" in err, "报告失败没有留下日志"
        _no_new(before, after, "场景10")
        return "原异常仍是 ValueError，报告失败另有日志"

    def s11():
        before = _dirs()
        code, _, err, after = _call(module, report_exc=OSError("MOCK report failed"))
        assert code == 1, f"无原异常时报告失败应返回 1，实际 {code!r}"
        assert "REPORT-FAIL" in err, "报告失败没有留下日志"
        _no_new(before, after, "场景11")
        return "报告失败 → 退出码 1，目录已清理"

    def s12():
        before = _dirs()
        for index in range(3):
            result, _, _, after = _call(
                module, print_exc=ValueError(f"注入：第{index + 1}次打印异常"))
            assert isinstance(result, ValueError), f"打印异常未保留：{result!r}"
            _no_new(before, after, f"场景12 第{index + 1}次")
        return "连续 3 次打印异常，残留不累积"

    def s13():
        """stderr 自身损坏时，日志通路不得顶替原始业务异常。"""
        before = _dirs()

        class BrokenStderr:
            def write(self, *_args, **_kwargs):
                raise OSError("MOCK stderr failed")

            def flush(self):
                raise OSError("MOCK stderr failed")

        module.RESULTS.clear()
        raised: BaseException | None = None
        with mock.patch.object(module, "run",
                               side_effect=ValueError("MOCK original business failure")), \
                mock.patch.object(shutil, "rmtree",
                                  side_effect=PermissionError("MOCK denied")), \
                mock.patch.object(sys, "stderr", BrokenStderr()):
            try:
                module.main([])
            except BaseException as error:  # noqa: BLE001 - 故障注入就是要接住它
                raised = error
        assert isinstance(raised, ValueError), f"stderr 异常替换了原始异常：{raised!r}"
        assert "MOCK original business failure" in str(raised), str(raised)
        leftover = _dirs() - before
        for name in leftover:  # 权限拒绝删除，残留是预期的，人工收尾
            shutil.rmtree(ROOT / "data" / name)
        return "stderr 损坏时仍抛原始 ValueError"

    scenario("1 创建目录后立即异常", s1)
    scenario("2 初始化阶段异常", s2)
    scenario("3 测试执行阶段异常", s3)
    scenario("4 连续三次异常不新增残留", s4)
    scenario("5 清理自身失败可观察", s5)
    scenario("6 原始异常优先于清理异常", s6)
    scenario("7 不误删其他测试目录", s7)
    scenario("8 实现里没有 ignore_errors", s8)
    scenario("9 预置同名目录不被覆盖删除", s9)
    scenario("10 报告异常不顶替原始异常", s10)
    scenario("11 仅报告失败时返回 1", s11)
    scenario("12 连续打印异常不累积", s12)
    scenario("13 stderr 故障不顶替原始异常", s13)

    failures = [name for name, ok, _ in RESULTS if not ok]
    for name, ok, detail in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    print("-" * 66)
    print(f"{len(RESULTS) - len(failures)}/{len(RESULTS)} 通过")
    if failures:
        print("失败项：" + "、".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(1)
