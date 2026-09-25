# HL 清算地图（hl-liqmap）

纯静态单文件网页 + GitHub Actions 每6小时地址收割。浏览器直连 Hyperliquid 公开 API，无后端、无构建、无依赖。

## 许可证

本项目基于 [GNU Affero 通用公共许可证 v3.0 (AGPL-3.0)](LICENSE) 发布。
© 2026 xyz1367487。你可以自由使用、研究和修改本项目；但若你将修改后的版本作为网络服务向他人提供，必须以相同许可证公开你的完整源码。

线上地址：**https://xyz1367487.github.io/hl-liqmap/**

## 架构

```
index.html          页面（估算层 + watchlist 真实层 + 全网真实模式）
harvest.py          地址收割器（每6小时由 Actions 运行）
.github/workflows/harvest.yml   每6小时自动运行（UTC 00:10/06:10/12:10/18:10）+ 手动触发
data/addresses.json 已发现地址索引（addr -> first_seen 日期）
data/accounts.json  候选池（addr -> 快照账户值，≥$8k，页面按实时≥$10k 过滤）
```

## 工作原理

**页面（打开即看，全部浏览器端完成）：**
- **估算层**（半透明横条，`%OI`）：OI×标记价 × 杠杆分布假设 × 多空比例假设，简化强平公式现算。假设驱动的相对强度参考，非真实持仓。有真实数据时默认自动隐藏（可勾选“显示估算层”作对照）。
- **Watchlist 真实层**（实心横条，美元名义）：手动粘贴 0x 地址 → 链上 `clearinghouseState` 原值，`liquidationPx` 接口直接返回。名单只存本机浏览器 localStorage。
- **全网真实模式**：读仓库内 `data/accounts.json` 候选池 → 浏览器并发实时拉取 → 仅渲染实时账户值 ≥$10k 的账户。真实行默认按**离现价距离分桶聚合**（0-0.5% / 0.5-1% / 1-2% / 2-3% / 3-5% / 5-10% / 10-20% / 20%+，桶标签如“1-2%·47仓”），行数=桶数，地址再多不刷屏；勾选“逐地址显示”可展开（每侧最多 100 条，省略数在汇总行注明）。

**索引器（后台，每6小时一次）：**
1. 拉日成交 >$10M 币种（与 HL-UPERP-MONITOR 监控列表同源）；
2. WS 订阅这些币种的成交流，采集 300 秒，收割 `users` 字段地址；
3. 新地址 + 候选池中 $8k~$12k 缓冲带老地址，逐个查 `clearinghouseState` 账户值；
4. ≥$8k 进候选池，结果提交回仓库。

**诚实边界**：HL 没有"按余额枚举账户"的公开端点，索引只覆盖"采集开始后活跃过的地址"——"全网"= 已发现地址的全网。索引随时间饱和（实测约 15 个新地址/秒/10 币种）。

## 本地开发

```bash
# 冒烟测试（25 秒采集）
HARVEST_SECONDS=25 python3 harvest.py
```

## 运维

- 仓库需开启 **Settings → Actions → General → Workflow permissions → Read and write contents**（索引器回写 data/）
- 手动触发收割：仓库 Actions → harvest → Run workflow
- public 仓库 Actions 不限免费额度
