# HL 清算地图（hl-liqmap）

纯静态单文件网页，浏览器直连 Hyperliquid 公开 API，无后端、无构建、无依赖。

## 上线步骤（全程网页操作，约 3 分钟）

1. GitHub 新建 **public** repository（建议名 `hl-liqmap`）——public 仓库的 Actions 不限免费额度。
2. 仓库页 → **Add file → Upload files** → 把本目录两个文件拖进去：
   - `index.html`
   - `README.md`
   → Commit changes。
3. 仓库 **Settings → Pages** → Source 选 `Deploy from a branch` → Branch 选 `main` / `/(root)` → Save。
   半分钟后页面地址：`https://xyz1367487.github.io/hl-liqmap/`
4. 仓库 **Settings → Actions → General → Workflow permissions** → 选 **Read and write permissions** → Save。
   （索引器每天要往仓库回写数据文件，必须有写权限；此步在第二阶段接索引器之前做即可。）

## 页面说明

- **估算层**（半透明横条，显示 `%OI` = 占该币未平仓量比例）：选中币种的未平仓名义(OI×标记价) × 杠杆分布假设，按简化强平公式现算。**假设驱动的相对强度参考，不是真实持仓分布，也不是精确金额**。
- **真实层**（不透明实心横条，显示美元名义）：Watchlist 粘贴 0x 地址 → 逐个拉取链上 `clearinghouseState` → `liquidationPx` 为接口原值。名单只存你自己浏览器的 localStorage。
- 币种范围：日成交 > $10M（约 70+ 个，与 HL-UPERP-MONITOR 监控列表同源）。
- 10 秒自动刷新（估算层）；Watchlist 手动拉取，避免频繁请求。
- 公开成交流无爆仓标记，本页不展示已成交爆仓事件。

## 第二阶段（索引器，待页面效果确认后）

GitHub Actions 每日一次：订阅 WS 成交流收割地址 → 合并地址索引 → 提交回仓库。
页面后续增加"全网真实模式"：读取仓库内地址索引，打开页面时批量拉取 >$10k 账户的真实仓位（真实层天然带多空方向，上线后估算层降级为对照）。
