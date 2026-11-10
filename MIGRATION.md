# 私有采集、公开聚合迁移指南（public index 待切换）

阶段状态：北京时间 2026-11-11（UTC+08:00）。私有采集、快照、导出归档与 state 回写已由交接记录核实成功；旧公开 harvest/snapshot 已 guard，不再定时写入。单仓库 deploy key 自动发布 aggregate 的实现已交付，真实 SSH 发布与公开分支结果仍待主线程核验。public index 尚未切换，后续主线程确认时再更新状态；不能写成全流程上线已成功。本轮仅整理本地文档，不推送、不删除或移除 main/snap 数据、不重写历史。旧 data/ 和 snap 仍公开，停止新写入不会撤回旧数据。

2026-11-10 UTC 的本地准备、算法及 SSH mock 验证是较早阶段；2026-11-11 北京时间的线上阶段记录见 VERIFICATION.md。首次成功私有运行跳过了公开发布；后续 SSH 验证 run 最后记录仍在运行中，二者不能合并为发布成功。

## 最小架构

- 公开仓库：index.html、采集/导出源码、测试、文档。公开 CI 只运行内存合成数据测试；不配置私有仓库凭据、不 checkout 私有仓库。
- 私有仓库：state/addresses.json、state/accounts.json、state/coins.json、state/volume_cache.json、state/snapshot.json、不可变 snapshots/<run-id>-<attempt>/ 原始快照和参考行情、采集 Actions 日志。只有私有工作流调用账户 API。
- 私有侧 aggregate.py 产生经过白名单验证的 exports/<generation>/aggregate.json。公开消费者只有独立 aggregate 分支的 data/aggregate.json。
- publish_aggregate.py 再次验证输出，仅写固定公开仓库的 aggregate 分支；普通追加提交，不强推、不 checkout 公共历史，不接受任意路径或附带文件。首次建立无父提交的数据分支；已有分支若含其他文件则拒绝操作。
- 无登录系统、无新后端。用户自行粘贴的本机 Watchlist 功能保留，不接触私有采集池。

## 保留的业务规则

收割 cron `40 1,7,13,19 * * *`，快照 cron `13,43 * * * *`；GitHub 调度可能延迟。
收割默认300秒、60秒分段、连续失败5次停止；主 dex+xyz；avg_7d>500万美元、同日成交缓存；候选池8000美元；8000–12000缓冲带复查；≥12000且最近复查日期超过3天的账户随机抽10%。注意原实现是每次随机抽10%，不保证3天覆盖全部。
快照预筛候选池最近账户值≥10000，实时查询仍≥10000才保留；双 dex，监控币种过滤，6并发及0.35秒 pacing，失败重试与 xyz 失败保留主 dex 的规则保持。

## 公开 schema v1 与地图

根字段仅 `schema_version`、`generated_at_unix`、`privacy`、`coin_list`、`markets`。
每市场仅 `reference_mark`、`buckets`；每桶仅 `side`、`band`（0–13）、`notional`、`positions`、`px_low`、`px_high`。不含账户值、地址、单仓数量、入场价、杠杆、账户分组或不可审查的透传 metadata。

原图按币种、方向、`abs(liqPx-mark)/mark` 的14档左闭右开距离带分桶，累计绝对美元名义、仓位数、价格极值。新导出用同样算法；多头显示 px_high、空头显示 px_low，平方根刻度、估算开关、多空滑块、币种切换、手动与10秒行情刷新保留。真实桶按私有端导出时的 reference_mark 固定，页面显示该参考价，下一次聚合快照更新；不伪装成随最新行情精确重分桶。精确动态重分需要公开逐仓信息或引入在线私有聚合服务，此最小架构不提供。

私有端生成时间与读取参考行情存在采集时差，原始快照与 marks 一并归档供对照。前端每30分钟获取新聚合，缓存最多使用6小时，超过2小时显示停滞提示；抓取失败保留旧图并显示失败。旧版 liqmap_net_cache 保留但不读取。新缓存键 liqmap_aggregate_v1。

## 聚合公开范围与实际隐私边界（修正后）

公开全部原算法非空桶，不按贡献账户数或金额筛桶，不设置替代门槛。`privacy` 固定为 `{"scope":"aggregate_only","buckets":"all_nonempty"}`，说明数据范围，不代表匿名保证。`positions` 是桶内仓位数量，必须是正整数；这是非空桶的结构定义，不是新增业务阈值。原有账户权益≥10000、监控币种、有效强平价与14档分桶规则保持；同一参考行情下地图数值与原 JS 一致。汇总累计全部可定位非空桶，不再因贡献人数抑制任何桶或总量；无效/缺失强平价仍按原地图规则不上图，当前汇总仅代表可定位桶名义，并非含无法定位仓位的账户总名义。

仅保护完整地址索引和原始逐账户文件。公开 schema 不含地址、账户列表、稳定账户标识、逐账户权益及逐账户仓位记录，但不保证聚合数据不可推断个别账户；用户未要求绝对匿名。单人贡献桶会保留其原始金额、仓位数量及价格极值，可与公开链上信息或交易所公开 API 关联；跨期差分、币种关联及已知仓位也可能揭示个别账户活动。真实样本的1092桶包含256个单人贡献桶，全部公开是本次明确授权的聚合范围。旧公开地址池和快照也会增加关联可能，迁移不能撤回第三方下载。

旧 k=3 方案及“低密度桶不计入汇总”属于未授权改动，已取消；旧633桶验证只覆盖筛选后子集，不是原图全量通过。原记录保留在 VERIFICATION.md 的已取代部分。

## 私有仓库安装与运行

私有采集库已建立并完成首次 state 回写；不要重复初始化或用旧本地种子覆盖新 state。首次安装或恢复时，先通过 GitHub API 核实 private=true，才能复制原数据。私有目录根放 harvest.py、aggregate.py、private_export.py、publish_aggregate.py；原四份 main 数据放 state/，snap 快照放 state/snapshot.json，并保存种子归档；deploy/private-collect.yml 复制为 .github/workflows/collect.yml。

采集仅要求 repository.private=true，不需要 repository 变量。main 的 push 仅在 initialize-private.sh 或 .github/workflows/collect.yml 变化时触发，执行 harvest → snapshot → export，一次完整初始化验证；state/snapshots 回写不匹配路径，且 GITHUB_TOKEN 回写不会递归触发。后续 cron 保持原规则：harvest 只更新池，不写快照；下一次 snapshot schedule 更新快照并导出。不要为首次验证再手工 dispatch 或重复推工作流。之后主动修改这两个文件也会触发一次完整验证。

发布 job env 的 ENABLE_PUBLIC_EXPORT 取 PUBLIC_AGGREGATE_SSH_KEY 或 PUBLIC_AGGREGATE_TOKEN 任一非空布尔值，step if 使用该 env，两项 secret 仅在发布 step 注入。无 secret 时跳过发布，采集及归档继续；配置后下一次成功 export 自动发布，无需 repository 变量。SSH key 非空优先，SSH 失败不降级 token。
- PUBLIC_AGGREGATE_SSH_KEY：单仓库 deploy key 自动发布通道；安装及真实发布验收以主线程后续核验为准，不因本地测试通过标为线上成功。公钥仅挂公开 hl-liqmap Deploy keys，开启 Allow write access（该仓库读写，不涉及其他仓库/私有采集库），私钥只存私有采集仓库 Actions secret。仓库权限宽于单分支，固定 aggregate/data/aggregate.json 的边界由脚本保障。私有 state 回写仍使用私有 GITHUB_TOKEN。
- SSH 默认 TLS 校验 HTTPS api.github.com/meta，按 ssh_keys 写 known_hosts，StrictHostKeyChecking=yes；独立临时裸仓库用 hash-object/mktree/commit-tree，不 git add 工作区。key 文件600、目录700，子进程输出捕获且只报固定安全错误；runner 临时目录保留。既有分支精确检查 tree，仅 data/ 和常规 data/aggregate.json 允许，额外文件、空目录、symlink 或 submodule 均拒绝。首个 commit 无父，有 tip 则继承；普通非强推，竞态失败留下一轮。
- PUBLIC_AGGREGATE_TOKEN：仅授权公开 hl-liqmap 的 Contents 写权限的细粒度 token/GitHub App token；只在私有仓库设置，不放进代码。脚本固定写 aggregate，仓库权限仍比单分支宽，必要时用仓库规则限制。私有 state 回写使用该私有仓库自带 GITHUB_TOKEN。

私有 Actions 需要 Contents write；保护 main 时需配置允许 bot 的专用规则。不要把真实日志、缓存、快照作为公开 Actions artifact 上传。

本地在新的私有工作目录运行，先准备 state 数据，保持旧目录备份：

```sh
PRIVATE_DATA_DIR="$PWD/state" python3 -B harvest.py
PRIVATE_DATA_DIR="$PWD/state" python3 -B harvest.py --snapshot
PRIVATE_DATA_DIR="$PWD/state" python3 -B private_export.py
python3 -B aggregate.py --validate exports/<generation>/aggregate.json
```

未设置 PRIVATE_DATA_DIR，或指向源码同目录 data/ 时采集器拒绝运行。导出生成目录使用独占创建，避免覆盖前次输出。

## 分阶段切换（2026-11-11 北京时间状态；保留后续步骤）

已核实私有首次采集、快照、导出和 state 回写完成；旧公开任务已 guard，无定时写入。以下初始化步骤仅供阶段追溯或恢复参考，不重复执行；SSH 真实发布结果和 public index 切换仍待主线程确认。

1. 主线程上传前刷新远端 main 的 data/addresses.json、data/accounts.json、data/coins.json、data/volume_cache.json 到私有 state 对应路径；本地2026-11-10快照和 marks 仅为种子，不是最新数据。
2. 通过 MCP 一次上传私有初始化清单（见 UPLOAD_CHECKLIST.md），确认 private=true。main 首次 push 自动完成一次 harvest + snapshot + export；等待该次运行，不再额外 dispatch。
3. 将已授权的公开 harvest/snapshot guard 合并到 main，检查原先已在运行的旧任务状态，避免其继续写公开数据；不删除 data 或改写历史。
4. 审查实际新 export；SSH key 或 token 任一非空且 export 成功后，工作流自动发布 aggregate。不能仅因 token 缺失判定跳过（SSH key 可独立发布）。主线程须核验真实发布 step、公开 aggregate:data/aggregate.json 的 schema、生成时间、唯一文件 tree 与提交父节点。public index 当前尚未切换；待上述结果及主线程确认后另行切换并记录日期，不额外 dispatch，不把本地旧种子当作新线上结果。
5. 不执行下表中的数据移除提案；用户本次明确要求保留原 data 和历史。

## 必须另行确认的操作与恢复方式

数据移除及 public index 切换尚未执行；旧公开任务 guard 已完成。以下保留操作影响与恢复参考，未来执行前须重核最新清单及授权，本轮不执行：

| 对象 | 拟议操作与影响 | 恢复方式 |
| --- | --- | --- |
| 公开 main:data/addresses.json（基线 bc13b9c） | 在新提交中移除跟踪/公开地址索引；本地文件保留，不先运行 git rm | 从该基线 git show 恢复，或私有种子归档复制 |
| 公开 main:data/accounts.json（同基线） | 在新提交中移除候选池文件；本地保留 | 同上 |
| 公开 snap:data/snapshot.json（基线 55d471b） | 移除当前公开逐账户快照；不自动删分支 | 从该基线或私有 seed 快照恢复；恢复会再公开 |
| 原公开 harvest/snapshot 工作流 | 已 guard，不再定时采集或写公开数据；旧运行是否全部结束须另核 | 恢复 bc13b9c 的对应 workflow；会恢复公开写数据风险 |
| 公开 index.html 与 aggregate 分支 | 部署新前端、首次公开聚合输出 | 回退到已知代码提交；回退旧前端会恢复旧公开数据读取 |

现有 coins.json 与 volume_cache.json 当前未检出地址，可保留；没有请求删除它们。历史重写、删分支、删 Actions 日志/运行记录、清理缓存或本机文件不在本次授权内；本次不拟执行这些操作。若另行要做，必须先按实时展开的路径/运行ID清单确认；历史重写和外部缓存清除无法保证完整恢复或撤回。

.gitignore 不会让已跟踪数据消失。本分支原 data/ 文件保持原样，不 stage，不运行 git add .。任何公开新提交前，检查 staged blob 的地址模式与私有字段，并核对 changed paths 仅源码/测试/文档。不要从包含原历史的仓库直接推成所谓“干净新公开仓库”。


## 2026-11-11 线上切换完成记录（北京时间）

私有运行 42857496914 已成功完成收割、快照、归档、state 回写与 SSH 聚合发布；私有 state 提交为 75bd2c10f2c56528f5eb60b4c611a66d3ccf561a。公开 aggregate 初次提交 ffc46e6cb522540554f0ef9d1d3d6ba581d063a1 只有 data/aggregate.json；真实输出 87 市场、1108 桶，生成时间 00:55:32，严格 schema 通过，地址模式 0 处。上述数量为该次快照，不是固定值。

公开前端已由 9bcfcf59d7434460f7525f493ffb8db3a9904de2 切换到聚合入口；源码 CI 42859744810、Pages 42859743580 均成功。线上浏览器已读取该新聚合时间，资源记录没有旧 accounts/addresses/snap 请求。两处残留三账户门槛说明已修正为全部非空桶公开；实际导出此前已经无该门槛。本条记录取代前文“前端尚未切换/SSH 发布待验证”的阶段状态。

旧公开 main:data/addresses.json、main:data/accounts.json 和 snap:data/snapshot.json 仍保留，待用户确认具体移除操作；Git 历史未重写。这次切换停止未来公开采集地址，但不代表旧地址数据已经保密。公开聚合不提供绝对匿名保证。
