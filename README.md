# HL 清算地图（hl-liqmap）

纯静态单文件网页 + GitHub Actions 每6小时地址收割。浏览器直连 Hyperliquid 公开 API，无后端、无构建、无依赖。

## 许可证

本项目基于 [GNU Affero 通用公共许可证 v3.0 (AGPL-3.0)](LICENSE) 发布。
© 2026 xyz1367487。你可以自由使用、研究和修改本项目；但若你将修改后的版本作为网络服务向他人提供，必须以相同许可证公开你的完整源码。

线上地址：**https://xyz1367487.github.io/hl-liqmap/**

## 架构

```
index.html                    页面（估算层 + watchlist 真实层 + 全网真实模式）
harvest.py                    地址收割器（每6小时）+ 快照生成器（--snapshot 模式，每30分钟）
.github/workflows/harvest.yml 每6小时自动运行（北京时间 09:40/15:40/21:40/03:40）+ 手动触发
.github/workflows/snapshot.yml 每30分钟自动运行（北京时间每 :13/:43，错开整点高峰）+ 手动触发
data/addresses.json           已发现地址索引（addr -> first_seen 日期）
data/accounts.json            候选池（addr -> 快照账户值，≥$8k，页面按实时≥$10k 过滤）
snap 分支 data/snapshot.json  全池双dex仓位快照（孤儿分支单提交强推，无 git 历史膨胀；页面打开秒读）
```

## 工作原理

**页面（打开即看，全部浏览器端完成）：**
- **估算层**（半透明横条，`%OI`）：OI×标记价 × 杠杆分布假设 × 多空比例假设，简化强平公式现算。假设驱动的相对强度参考，非真实持仓。有真实数据时默认自动隐藏（可勾选“显示估算层”作对照）。
- **Watchlist 真实层**（实心横条，美元名义）：手动粘贴 0x 地址 → 链上 `clearinghouseState` 原值，`liquidationPx` 接口直接返回。名单只存本机浏览器 localStorage。
- **全网真实模式**：**默认走仓库快照（方案B）**——页面打开自动读 `snap` 分支的 `data/snapshot.json`（snapshot.yml 每 30 分钟对候选池全量双 dex 拉取生成，约 1.5MB），秒渲染全部币种的图表/汇总/表格；新鲜度 = 快照生成时间（netMeta 行标注，停滞超 2 小时警告），浮动盈亏按当前标记价现算。**"拉取全网实时"按钮**保留：随时全量实时拉取（并发 16，每地址双 dex，失败重试 ×2，进度条带速率与 ETA）。真实行按**离现价距离分桶聚合**（0-0.5% / 0.5-1% / 1-2% / 2-3% / 3-5% / 5-10% / 10-20% / 20%+）；勾选"逐地址显示"可展开（每侧最多 100 条）。快照不可用（首次部署/任务故障）时退回本机 localStorage 缓存（6 小时内）并后台静默刷新；均不可用才需手动点按钮。

**索引器（后台，每6小时一次）：**
1. 拉取近 7 日日均成交额 > $5M 的币种（**avg_7d 口径，与 HL-UPERP-MONITOR 一致**；主 dex + xyz 双 dex；`data/volume_cache.json` 日级缓存，结果写 `data/coins.json` 供页面读取；xyz-only 交易者也能进索引）；
2. WS 订阅这些币种的成交流，**分段采集 300 秒**（默认 5×60s，段间重连、断线自动续采，连续失败 5 次才带着已有地址收工），收割 `users` 字段地址；
3. 新地址 + 候选池中 $8k~$12k 缓冲带老地址，逐个查 `clearinghouseState` 账户值（主 dex 的 accountValue = 账户总值，含 xyz 子账户）；
4. ≥$8k 进候选池，**收割统计**（queried/ok/failed/fail_rate/segments/run_seconds 等）写入 `data/accounts.json` 的 `stats` 字段，页面“全网真实模式”顶部显示上次收割成功率；
5. 结果提交回仓库。

**诚实边界**：HL 没有"按余额枚举账户"的公开端点，索引只覆盖"采集开始后活跃过的地址"——"全网"= 已发现地址的全网。索引随时间饱和（实测约 15 个新地址/秒/10 币种）。

## 本地开发

```bash
# 冒烟测试（25 秒采集）
HARVEST_SECONDS=25 python3 harvest.py
# 快照模式冒烟（只拉前 60 个地址）
HARVEST_SNAPSHOT_LIMIT=60 python3 harvest.py --snapshot
```

## 运维

- 仓库需开启 **Settings → Actions → General → Workflow permissions → Read and write contents**（索引器回写 data/）
- 手动触发收割：仓库 Actions → harvest → Run workflow
- public 仓库 Actions 不限免费额度
