# 使用的模型与版本参考（models-reference 分支）

> 本分支专门记录实际接入并编排的模型型号与版本（倍率快照），供参考与复现。
> 倍率来自 WorkBuddy 账号目录 `/v1/models` 实时返回的 `credits` 字段，会随优惠窗口波动，以实时返回为准。

## 版本基准

- workbuddy2api 面板分支：`v1.10.0`（2026-09-16，同步上游 Sliverkiss/workbuddy2api commit `76bb543`）
- 自加 patch：auto 调度层（`auto_model` + `model_fallback`）+ GLM `reasoning_effort=low` 注入（2026-09-17 重建镜像）

## 轮换模型清单（核心 5 个）

| 型号（model id） | credits 倍率 | 角色 | 说明 |
|---|---|---|---|
| `cn:hy3` | x0.00（免费） | 日间主模型 | 日间主力，薅免费额度 |
| `cn:deepseek-v4.1-flash` | x0.03 | 降级档 1 | 最便宜的付费档 |
| `cn:glm-5.3-flash` | x0.06 | 降级档 2 | 1M 上下文、支持看图/看视频；需 `reasoning_effort=low` 防空回复 |
| `cn:hy3-x` | x0.05 | 兜底 | 链末兜底 |
| `cn:hy4-preview` | 夜间免费（日间 x0.29） | 夜间主模型 | 23:00–08:00 免费窗口 |

## 轮换链

- **日间（08:00–23:00）**：`cn:hy3` → `cn:deepseek-v4.1-flash` → `cn:glm-5.3-flash` → `cn:hy3-x`
- **夜间（23:00–08:00）**：`cn:hy4-preview`（同级降级同日间链；08:00 自动切回 `cn:hy3`）

## 同目录下其他可用模型（部分，未进轮换链）

| 型号 | credits | 备注 |
|---|---|---|
| `cn:minimax-m3` | x0.25 | — |
| `cn:kimi-k2.6` | x0.52 | — |
| `cn:kimi-k3-1` | x1.62 | 贵 |
| `cn:glm-5.2` | x0.79 | — |
| `cn:glm-5.1` | x0.79 | — |

> 接入方式：workbuddy2api 的 `auths/` 账号池（多个 WorkBuddy 账号）→ 统一暴露为 `cn:*` 模型名。
> 客户端（WorkBuddy / OpenClaw）通过 provider `baseUrl=http://<nas>:7863/v1` + apiKey 接入。
