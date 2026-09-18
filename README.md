# workbuddy2api-rotation（增强版 · auto 模型自动轮换/降级编排）

> ⚠️ **这是一个在 workbuddy2api 基础上自行 patch 的增强版**，不是原版上游。
> 它在原版之上加了一层「auto 虚拟模型自动调度」能力（昼夜主模型切换 + 请求级降级链 + GLM 空回复补丁）。
> 原版上游**没有** `auto_model` / `model_fallback` 这两个配置段（未知键会被静默忽略）。

---

## 上游引用（致谢）

本仓库基于以下两个上游项目，感谢作者们的维护：

- **上游核心**：[Sliverkiss/workbuddy2api](https://github.com/Sliverkiss/workbuddy2api)（MIT）—— wb2api 本体，账号池轮换、成本账本、`/v1/models` 实时 `credits` 透出等均来自此处。
- **面板分支**：[linguo2625469/workbuddy2api-panel](https://github.com/linguo2625469/workbuddy2api-panel)（MIT）—— 带 Web 面板的部署形态，本仓库部署即基于此分支。

**版本基准**：面板分支 `v1.10.0`（2026-09-16，已同步上游至 commit `76bb543`） + 本仓库自加 patch。
（wb2api 上游无 release tag，按 commit 跟踪；本文档 patch 于 2026-09-17 在 NAS 上重建镜像生效。）

**特别感谢**：上游在 Issue 反馈中确认了 GLM 空回复的行为面，并表示会在文档与注入策略上跟进修复；同时对「读实时 `credits` 排序、把降级链放在下游」的思路表示认同。本仓库即这一思路的下游实践实现。🙏

---

## 本增强版相对原版增加了什么

| 能力 | 原版上游 | 本增强版 |
|---|---|---|
| `auto` 虚拟模型 | ❌ 无 | ✅ 有（`auto_model` 昼夜主模型切换） |
| 请求级降级链 `model_fallback` | ❌ 无（限流走账号轮换） | ✅ 有（被限流/额度耗尽自动掉下一档） |
| GLM 空回复修复 | 仅 deepseek 系 thinking 注入 | ✅ 对 `glm-5.3-flash` 注入 `reasoning_effort=low` |
| 账号池 / 成本账本 / 实时 credits | ✅ 原生 | ✅ 原生（未改动） |

> 上游的定位是「做好 chat 出口，fallback 留给下游」——这是合理的架构选择。本仓库是把"降级链"这一层**显式实现在下游（NAS 本地编排脚本）**，作为上游思路的落地参考。

---

## 两层轮换

1. **请求级兜底（`model_fallback`）—— 用完自动切换**
   某真实模型被软限流（HTTP 6004）/ 额度耗尽（402）时，自动把请求重写到链上下一档并重试。

2. **时间级主模型切换（`auto_model.day_primary`）—— 到点自动切换**
   按北京时间在「日间主模型 / 夜间主模型」间切换（夜间老用户免费窗口用 `cn:hy4-preview`）。
   优惠到期时，用 cron / 系统定时任务触发 `deadline_switch.py` 重写 `day_primary`。

### 原则
- **优惠到期 ≠ 抛弃**：仍比原价便宜的模型留在链里。
- **不臆测未来定价**：脚本读 `/v1/models` 实时 `credits` 倍率来重排。

---

## 使用的模型与版本（参考）

以下为本人实际接入并编排的模型（经 WorkBuddy 账号目录，`/v1/models` 透出的 `credits` 倍率，2026-09 实测）：

| 型号（model id） | credits 倍率 | 角色 | 说明 |
|---|---|---|---|
| `cn:hy3` | x0.00（免费） | 日间主模型 | 日间主力，薅免费额度 |
| `cn:deepseek-v4.1-flash` | x0.03 | 降级档 1 | 最便宜的付费档 |
| `cn:glm-5.3-flash` | x0.06 | 降级档 2 | 1M 上下文、支持看图/看视频 |
| `cn:hy3-x` | x0.05 | 兜底 | 链末兜底 |
| `cn:hy4-preview` | 夜间免费（日间 x0.29） | 夜间主模型 | 23:00–08:00 免费窗口 |

**轮换链**：日间 `hy3 → deepseek → glm-5.3-flash → hy3-x`；夜间 `hy4-preview`（同级降级同日间链）。

> 倍率会随优惠窗口波动，以 `/v1/models` 实时返回为准；本表仅作参考快照。
> 更完整的型号/版本清单见分支 [`models-reference`](../../tree/models-reference)。

---

## 快速开始

1. 部署 workbuddy2api（建议基于面板分支，见上游引用）。
2. 把本仓库的 `auto_model` + `model_fallback` 两段（需自行 patch 源码支持，或仅作下游编排参考）并入 `config.json`。
3. 用 `deadline_switch.py` 在优惠到期日自动重排日间链（详见脚本内 `--simulate` / `--credits` / `--force`）。

## 文件

- `deadline_switch.py`：数据驱动的切换脚本（Python 3.8+，仅标准库）
- `examples/config.auto.json`：配置示例
- `examples/crontab.example`：定时任务示例
- 分支 `models-reference`：模型与版本参考清单

## 许可证

MIT（与上游一致）。
