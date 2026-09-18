#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wb2api auto 虚拟模型降级/轮换 配置脚本（通用版）
================================================
两层轮换：
  1) 请求级兜底（model_fallback）：某模型被限流(6004)/额度耗尽(402) -> 自动切下一档
  2) 时间级主模型切换（auto_model.day_primary）：到点（如免费窗口结束）改日间主力

实时倍率(credits)从 /v1/models 读取，仅作参考与异常提示；白天链采用人工指定顺序
（免费优先 -> 最便宜 -> 能力更强 -> 兜底），不随倍率自动重排。
优惠到期后仍便宜的档位不丢。

本脚本只负责「编排 + 落地」：
  - 读 / 写本地 config.json（路径由 WB2API_CONFIG 指定）
  - 验证走 HTTP 到 WB2API_HOST
  - 如需推到远端 NAS，把 apply_config() 换成你的 SSH / 部署方式

依赖：Python 3.8+，仅标准库（urllib）。
原项目：https://github.com/Sliverkiss/workbuddy2api

用法：
  python deadline_switch.py                    # 应用人工顺序（无变化则安全退出）
  python deadline_switch.py --simulate         # 只打印将写入的配置，不落地
  python deadline_switch.py --credits "cn:deepseek-v4.1-flash=0.17"  # 假设涨价的演练
  python deadline_switch.py --force after0930  # 强切到指定阶段
"""
import sys, os, json, datetime, time, tempfile, shutil, base64, urllib.request, urllib.error

# ── 配置（全部可经环境变量覆盖）────────────────────────────
HOST        = os.getenv("WB2API_HOST", "127.0.0.1")
PORT        = os.getenv("WB2API_PORT", "7863")
API_KEY     = os.getenv("WB2API_API_KEY", "")          # 留空则不带鉴权头
CONFIG_PATH = os.getenv("WB2API_CONFIG", "/vol4/workbuddy2api/data/config.json")
# 落地后是否执行一条重启命令（如 "ssh nas docker restart workbuddy2api"）；留空则跳过
RESTART_CMD = os.getenv("WB2API_RESTART_CMD", "")
# 优惠到期日（按你的实际优惠窗口修改）
D0923 = datetime.date(2026, 9, 23)   # 例：某档 0.03x 优惠截止
D0930 = datetime.date(2026, 10, 1)   # 例：免费档截止，之后转付费

# 白天降级顺序（人工指定，C 方案：免费优先 -> 最便宜 -> 能力更强 -> 兜底）
#   cn:hy3                 免费，日间主力
#   cn:deepseek-v4.1-flash 最便宜的付费档
#   cn:glm-5.3-flash       能力更强：1M 上下文、支持看图看视频
#   cn:hy3-x               兜底
# 接 GLM 时务必确认上游已注入 reasoning_effort=low，否则空回复会卡住（见 README）。
MANUAL_DAY_CHAIN = ["cn:hy3", "cn:deepseek-v4.1-flash", "cn:glm-5.3-flash", "cn:hy3-x"]


def _http_json(url, timeout=30):
    req = urllib.request.Request(url)
    if API_KEY:
        req.add_header("Authorization", f"Bearer {API_KEY}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def phase_for(today):
    if today >= D0930:
        return "after0930"
    if today >= D0923:
        return "after0923"
    return "before"


def fetch_credits():
    """从 /v1/models 读各模型实时消耗倍率（x0.03 -> 0.03）。读不到返回 None。"""
    try:
        raw = _http_json(f"http://{HOST}:{PORT}/v1/models")
    except Exception:
        return None
    try:
        d = json.loads(raw)
        items = d.get("data", d) if isinstance(d, dict) else d
    except Exception:
        return None
    res = {}
    for m in items:
        if not isinstance(m, dict):
            continue
        mid, cr = m.get("id"), m.get("credits")
        if not mid or cr is None:
            continue
        try:
            res[mid] = float(str(cr).lstrip("xX"))
        except ValueError:
            continue
    return res or None


def build_day_chain(credits):
    """返回白天降级顺序：人工指定（MANUAL_DAY_CHAIN），不随倍率自动重排。
    若读得到实时倍率，会剔除其中已不存在的模型；读不到则原样返回。"""
    if not credits:
        return list(MANUAL_DAY_CHAIN)
    chain = [m for m in MANUAL_DAY_CHAIN if m in credits]
    return chain or list(MANUAL_DAY_CHAIN)


def suggest_by_credits(credits):
    """纯按实时倍率升序的建议顺序，仅用于日志对比/异常提示（不落盘）。"""
    if not credits:
        return []
    pool = [m for m in MANUAL_DAY_CHAIN if m in credits]
    return sorted(pool, key=lambda m: credits[m])


def desired_auto(phase, credits=None):
    base = {"enabled": True, "night_primary": "cn:hy4-preview",
            "day_primary": "cn:hy3", "night_start": 23, "night_end": 8}
    chain = build_day_chain(credits)
    if not chain:
        return base
    # before：免费首档 hy3 作主模型
    # after0923 / after0930：免费窗口已结束，主模型落到链上下一个仍便宜的档
    #   （优惠到期≠抛弃，仍比原价便宜就留；按人工 C 方案顺序选下一档）
    if phase == "before":
        base["day_primary"] = chain[0]
    else:
        base["day_primary"] = chain[1] if len(chain) > 1 else chain[0]
    return base


def desired_fallback(phase, credits=None):
    # 候选档位全部保留（优惠到期≠没优惠，只要有优惠就不抛弃）
    chain = build_day_chain(credits)
    fb = {}
    for i, m in enumerate(chain):
        nxt = list(chain[i + 1:])
        if nxt:  # 末档不写空列表，保持与线上格式一致
            fb[m] = nxt
    fb["cn:hy4-preview"] = list(chain)
    return fb


# ── 本地 config 读写（远端场景请换成你的 SSH / 部署逻辑）────
def load_local_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return f.read()


def apply_config(cfg):
    """写回本地 config.json。若 config 在远端 NAS，把这里换成你的部署方式。
    临时文件放在 config 同目录，避免跨设备 rename（os.replace 在 /tmp→/vol 会 Invalid cross-device link）。"""
    d = os.path.dirname(CONFIG_PATH) or "."
    fd, lp = tempfile.mkstemp(suffix=".json", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        shutil.move(lp, CONFIG_PATH)   # 跨设备安全
    except Exception:
        try:
            os.remove(lp)
        except OSError:
            pass
        raise


# ── 验证 ──────────────────────────────────────────────────
def verify():
    for _ in range(20):
        try:
            code = _http_json(
                f"http://{HOST}:{PORT}/v1/models")
            if code:
                chat_body = json.dumps({"model": "auto",
                                         "messages": [{"role": "user", "content": "ping"}],
                                         "max_tokens": 16}).encode("utf-8")
                req = urllib.request.Request(
                    f"http://{HOST}:{PORT}/v1/chat/completions",
                    data=chat_body, method="POST")
                req.add_header("Content-Type", "application/json")
                if API_KEY:
                    req.add_header("Authorization", f"Bearer {API_KEY}")
                with urllib.request.urlopen(req, timeout=60) as r:
                    return True, f"models=ok chat={r.status}"
        except Exception as e:
            pass
        time.sleep(2)
    return False, "models endpoint 始终无响应"


def _restart():
    if not RESTART_CMD:
        return
    import subprocess
    subprocess.run(RESTART_CMD, shell=True, timeout=120)


def main():
    args = sys.argv[1:]
    sim = "--simulate" in args
    force = None
    if "--force" in args:
        i = args.index("--force")
        force = args[i + 1] if i + 1 < len(args) else None
    if sim and force is None:
        i = args.index("--simulate")
        nxt = args[i + 1] if i + 1 < len(args) else None
        force = nxt if nxt and not nxt.startswith("--") else None

    override = {}
    if "--credits" in args:
        i = args.index("--credits")
        if i + 1 < len(args):
            for kv in args[i + 1].split(","):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    try:
                        override[k.strip()] = float(v.strip())
                    except ValueError:
                        pass

    today = datetime.date.today()
    phase = force or phase_for(today)
    print(f"[deadline_switch] today={today} phase={phase} sim={sim} force={force}")

    raw = load_local_config()
    cfg = json.loads(raw)

    credits = fetch_credits()
    if credits is None:
        print("[deadline_switch] 警告：读不到实时倍率，回退默认顺序")
        credits = {}
    if override:
        credits.update(override)
        print(f"[deadline_switch] 演练覆盖倍率: {override}")
    print("[deadline_switch] 实时倍率:",
          {k: credits[k] for k in MANUAL_DAY_CHAIN if k in credits})
    chain = build_day_chain(credits)
    print("[deadline_switch] 白天链(人工指定):", " -> ".join(chain))
    sug = suggest_by_credits(credits)
    if sug and sug != chain:
        print("[deadline_switch] 参考·纯按倍率排序应为:", " -> ".join(sug),
              "（当前采用人工顺序；若想改回省钱优先请调整 MANUAL_DAY_CHAIN）")

    orig_auto = cfg.get("auto_model")
    orig_fb = cfg.get("model_fallback")
    cfg["auto_model"] = desired_auto(phase, credits)
    cfg["model_fallback"] = desired_fallback(phase, credits)

    if cfg["auto_model"] == orig_auto and cfg["model_fallback"] == orig_fb:
        print("[deadline_switch] 目标配置与当前一致，无需改动，安全退出。")
        sys.exit(0)

    if sim:
        print("[deadline_switch] SIMULATE -> 将写入：")
        print(json.dumps({"auto_model": cfg["auto_model"],
                          "model_fallback": cfg["model_fallback"]},
                         ensure_ascii=False, indent=2))
        print("[deadline_switch] SIMULATE OK，未做任何改动。")
        sys.exit(0)

    # 备份 + 写回 + 重启 + 验证
    bk = CONFIG_PATH + f".bak_{today.isoformat()}"
    import shutil
    shutil.copy(CONFIG_PATH, bk)
    print(f"[deadline_switch] 已备份 -> {bk}")

    try:
        apply_config(cfg)
        _restart()
        print("[deadline_switch] 已写回并重启，开始验证...")
        ok, why = verify()
        if ok:
            print(f"[deadline_switch] 切换成功且链路验证通过。({why})")
            sys.exit(0)
        else:
            print(f"[deadline_switch] 验证失败({why})，回滚到备份并重启。")
            shutil.copy(bk, CONFIG_PATH)
            _restart()
            sys.exit(4)
    except Exception as e:
        print(f"[deadline_switch] ERROR: {e}")
        sys.exit(3)


if __name__ == "__main__":
    main()
