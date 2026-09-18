# wb2api 自动模型轮换 / 降级编排

> 配套 [Sliverkiss/workbuddy2api](https://github.com/Sliverkiss/workbuddy2api)（MIT）的 `auto` 虚拟模型能力，
> 把「优惠到期到点切换」和「额度耗尽自动降级」做成可复用的编排脚本。
> 同样适用于其面板分支 [linguo2625469/workbuddy2api-panel](https://github.com/linguo2625469/workbuddy2api-panel)。

## 它解决什么

wb2api 自带 `auto` 虚拟模型：一个 alias，后端按规则解析到真实模型。本仓库在它之上加了**两层轮换**：

1. **请求级兜底（用完自动切换）** —— `model_fallback`
   某真实模型被限流（HTTP 6004 软限流）或额度耗尽（402）时，wb2api 自动把请求重写到链上下一档并重试。
   配置在 `config.json` 的 `model_fallback`。

2. **时间级主模型切换（到点自动切换）** —— `auto_model.day_primary`
   `auto` 按北京时间在「日间主模型 / 夜间主模型」之间切换（例如夜间老用户免费窗口用 `cn:hy4-preview`）。
   优惠到期时，用定时任务（cron / WorkBuddy 自动化）重写 `day_primary`，实现「到点切到下一档」。

> **原则：优惠到期 ≠ 抛弃。** 仍比原价便宜的模型留在链里；切换脚本读实时 `credits` 倍率，绝不臆测未来定价。

## 快速开始

1. 部署 workbuddy2api（见上游 README），确保 `/v1/models` 返回各模型 `credits` 倍率。
2. 把 `examples/config.auto.json` 的 `auto_model` + `model_fallback` 两段并入你的 `config.json`，重启。
3. （可选）用 `deadline_switch.py` 在优惠到期日自动重排日间链：

   ```bash
   export WB2API_HOST=127.0.0.1
   export WB2API_PORT=7863
   export WB2API_API_KEY=你的key        # 留空则不带鉴权头
   export WB2API_CONFIG=/path/to/config.json
   python deadline_switch.py --simulate   # 先演练，不落盘
   python deadline_switch.py              # 落地（写回 config + 重启 + 验证）
   ```

## 配置示例

见 `examples/config.auto.json`：

```json
{
  "auto_model": {
    "enabled": true,
    "night_primary": "cn:hy4-preview",
    "day_primary": "cn:hy3",
    "night_start": 23,
    "night_end": 8
  },
  "model_fallback": {
    "cn:hy3": ["cn:deepseek-v4.1-flash", "cn:glm-5.3-flash", "cn:hy3-x"],
    "cn:deepseek-v4.1-flash": ["cn:glm-5.3-flash", "cn:hy3-x"],
    "cn:glm-5.3-flash": ["cn:hy3-x"],
    "cn:hy4-preview": ["cn:hy3", "cn:deepseek-v4.1-flash", "cn:glm-5.3-flash", "cn:hy3-x"]
  }
}
```

> 模型名（`cn:*`）取决于你接入的供应商，按需替换。上面的 `day_primary`/`night_primary` 与链顺序
> 体现的是「免费优先 → 最便宜 → 能力更强 → 兜底」的 C 方案思路（账号额度充裕时，能力优先于省钱）。

## deadline_switch.py

数据驱动：读 `/v1/models` 实时 `credits`，按人工指定顺序（`MANUAL_DAY_CHAIN`）编排日间链，
**优惠到期后仍便宜的档位不丢**。支持：

- `--simulate`：只打印将写入的配置，不落盘
- `--credits "cn:deepseek-v4.1-flash=0.17"`：假设某档涨价后的倍率提示
- `--force <phase>`：强切到指定阶段（`before` / `after0923` / `after0930`）

> **接入远端 NAS**：脚本默认读写本地 `WB2API_CONFIG` 路径、验证走 HTTP 到 `WB2API_HOST`。
> 若 config.json 在远端，把 `apply_config()` 改成你的 SSH / 部署方式（例如 `ssh nas "cp ..."`）即可。

## 已知坑：GLM-5.3-Flash 空回复

GLM-5.3-Flash 默认 `reasoning_effort=max`，思考 token 计入 `max_tokens` 预算 → 返回 **HTTP 200 但正文为空**，
且空回复**不触发降级**（会卡住）。

**修法（在 wb2api 转发层，不在本仓库）**：对 `glm-5.3-flash` 注入默认 `reasoning_effort=low`
（调用方显式指定时不覆盖）。补丁位于 wb2api 侧 `internal/server/handler.go` + `logging.go`。
本仓库只负责编排，不重复打这个补丁；若用了 GLM，请确认上游已处理，否则它在链里会卡空回复。

## 许可证

MIT（与上游一致）。
