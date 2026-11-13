## 2026-11-13 单仓位 >$5,000 本地验收（未部署）

本节取代下方历史门槛描述。本地公开 Python 24项、私有 Python 17项、JS 31项通过；包含严格5000/5000.01、低/负权益双dex大仓、两笔3000、大账户小仓、API失败保留候选、905地址多批重启/重试/退出再发现、fs/ls保持、时间预算与schema旧新兼容。公开CI现执行Python与Node两套。

真实旧私有快照共2770账户、22540仓位；其中10774仓位金额>5000（此数尚未叠加有效强平价和币种条件）。按完整图示条件重聚合，多头 $1,528,910,916.1595693、空头 $3,253,762,213.126789；schema1/2/3 两侧均守恒（浮点容差 rel=1e-12/abs=1e-5）。此为旧样本新算法核对，不是新口径全索引快照，不补写新标记。

真实API采样48地址（24候选+24历史），6 workers，48成功/0失败，8.073秒；23账户有合格仓，其中3个权益低于10000。按当前3128候选+400历史线性估算约593秒/轮。48地址本机小样本不能保证CI吞吐；失败重试、候选增长、限流、行情和导出增加时间。

实际索引85997，历史首轮约215轮；每轮100重试占满时约287轮，半小时有效触发约4.5–6天，指覆盖尝试而非全部成功。首轮后仍连续轮转；成功完成还需retry_pending清零。部署未执行，线上新队列未启动，不能声称已有回填进度。

Alma真实浏览器使用合成payload验收11项全部通过：筛选文案/freshness/双侧首屏、明确新增移除、杠杆隐藏累计不变、缩放累计不变、fixed tooltip及图框约束（允许2 CSS像素舍入）、真实鼠标拖动与守恒、xyz未知杠杆退化、行情失败参考价、旧口径与过期提示、Raw失败API回退、全部失败保留有效缓存。无真实地址公开fixture。

命令：`python3 -B -m unittest discover -s tests -v`（分别在public/private）；`node --test tests/*.test.cjs`（public）。本地证据仅交接目录 evidence/，不属于公开上传范围。原始日志中的mock发布成功文案不代表真实发布。本轮无push/dispatch/删除。

# 验证与交付记录

## 2026-11-11 北京时间阶段汇总（UTC+08:00；本轮仅文档核对）

本节根据本地 handoff、中文任务状态及本轮用户确认的事实整理；本轮没有远端查询或写入，没有重新运行下方历史测试。下方 2026-11-10 的记录及原文完整保留，只代表各自阶段；“尚未上线”“待安装”“原任务 active”等旧状态不覆盖本节。

- 2026-11-10 UTC：本地全部非空桶算法及浏览器对照通过；SSH 发布后端15项测试通过，其中远端调用为 mock，不能证明真实发布。
- 2026-11-11 00:20:54 北京时间交接：首次私有 run 42851322991 已完成，Harvest、Snapshot、Export/archive、Commit private state 成功；state 与 snapshots 回写已核实。该次公开发布因当时缺少凭据而跳过，并非已发布 aggregate。
- 2026-11-11 00:46:25 北京时间交接：后续 SSH 验证 run 42857496914（attempt 1）仍为 in_progress，Harvest 进行中，Snapshot、Export/archive、state 回写及公开发布 pending；未核验最终公开提交、tree、schema/地址检查或聚合生成时间。等待主线程后续确认，不额外 dispatch。
- 本轮事实确认：旧公开 harvest/snapshot 已 guard，不再定时写入；新私有任务每6小时收割、每30分钟快照并导出。单仓库 deploy key 自动发布 aggregate，仓库级读写权限与发布器的单分支/单文件约束须区分；真实 SSH 发布最终结果仍待核验。
- public index 尚未切换，后续主线程确认时再更新状态。旧公开 main:data/ 与 snap:data/snapshot.json 仍可访问，未清理、未重写历史。聚合端全部非空桶公开、固定 reference_mark；不意味着线上旧前端已完成切换，也不保证绝对匿名。

本轮仅修改必要文档，不上传真实地址、token 或 key 正文，不推送、不删除文件，不将阶段成功记为全流程上线成功。

## SSH 发布后端本轮验证（当前增量结果）

2026-11-10 UTC 本地执行，SSH deploy key 待 operator 安装或验证。本会话未读取真实凭据、未执行远端 push/上传/dispatch，未删除任何文件。原 REST bearer 保留，SSH key 非空优先；两份 gate 为 key/token 任一非空，仅发布 step 注入。采样、过滤、原7项测试保持原样。下方部署配置为先前历史结果，本轮以此段及 UPLOAD_CHECKLIST.md 增量表为准。

- `python3 -B -m unittest discover -s tests -v`：15项 PASS（原7 + 新8），1.090秒。远端 metadata/SSH/push 全 mock；本地真实 Git plumbing 检查最终单文件 tree、JSON、orphan/parent。
- SSH 测试覆盖既有分支其他文件、子模块、空目录拒绝；fetch 前分支变化中止；push拒绝仅一次、无 force/加号 refspec；subprocess输出及超时异常含合成密钥仍仅返回固定错误；schema/address校验先于SSH；Git环境隔离；严格host key、HTTPS默认TLS调用、私钥600及临时目录700。
- 私有副本同命令8项PASS（0.845秒）；两侧发布器及新增测试逐字节一致。两份工作流Ruby YAML解析、Python AST、24种发布条件组合（两份workflow × 两种key × 两种token × 三种export outcome）、step-only凭据注入及git diff --check均PASS。aggregate.py、harvest.py、private_export.py及原7测试与checkout HEAD逐字节一致。
- 首轮新增测试出现 fixture 的 FETCH_HEAD 创建方式及 NUL 结尾断言问题，修正测试后全部通过，未放宽实现边界。测试合成临时目录 aggregate-publish-* 按禁止删除规则保留在系统临时目录，不上传；以 -B 运行，不创建 pycache。
- 公钥仅挂公开 hl-liqmap 并启用 Allow write access，私钥仅私有采集库 PUBLIC_AGGREGATE_SSH_KEY。该权限是仓库级读写，脚本限定 aggregate/data/aggregate.json；不得称其是 GitHub 分支级 key。真实安装状态、线上SSH及最后 workflow 上传触发的一次已授权全流程待主线程核验。

## 部署配置本轮验证（用户已授权，尚未上线）

2026-11-10 本地执行。只修改部署配置和文档；没有网络采集、GitHub 上传、Actions dispatch、公开发布、历史修改或文件删除。主线程负责 MCP 上传。精确清单见 UPLOAD_CHECKLIST.md：私有 main 16份、公开 main 14份、公开 aggregate 单文件。已有 data 保留。

- 现有 unittest 7项全部 PASS，0.409秒。测试输出中的 published 来自 mock，不是外部发布。
- 实际 YAML 的5种事件/模式分支在 Node 中求值通过：push 为 harvest/snapshot/export 全部执行；harvest cron 与手动 harvest 只 harvest；snapshot cron 与手动 snapshot 只 snapshot/export。private=false 全部跳过。精确 main/path 过滤、state 回写路径不触发、原两项 cron 不变均通过。
- secret 布尔值 × export outcome 的6种发布条件通过：仅 true + success 发布。无 repository vars 引用；job env 仅公开判空布尔值，token 仅在发布 step 注入。publish_aggregate.py 继续使用由工作流自动传入的 ENABLE_PUBLIC_EXPORT env 防误用，不要求 repository variable。
- 5份 YAML Ruby 解析、2份 shell 的 sh -n、4份核心 Python AST 及两侧核心源码逐字节一致性通过；两份 collect 工作流一致。环境无 actionlint，未做 GitHub Actions 服务端运行验证。条件矩阵首次验证脚本因无 name 的 uses step 引发 TypeError；修正验证脚本的可选字段访问后完整矩阵通过，未为通过测试改变工作流。
- 公开 harvest/snapshot guard 无 schedule、contents:read，仅通知 job。前端聚合分支 URL 存在，旧地址池/候选池/snap URL 未出现。本轮未重做浏览器交互，下方保留此前证据。
- 公开 data/addresses.json、accounts.json、coins.json、volume_cache.json 与本地 origin/main 逐字节一致。没有刷新远端；主线程上传前必须刷新最新远端池，不能把本地样本当最新。
- 首个可公开种子输出 ../hl-liqmap-private-preparation/aggregate-reviewed.json 再次检查：87市场、1092桶、126090字节，地址模式0，严格 schema PASS；SHA256 dbb4127911f5cdfe3184c54255be9ba31daa7c770592a08cf2ef4b8cad6e217c。2026-11-10样本仅种子，首次真实私有 snapshot/export 将更新，尚未执行真实 harvest + snapshot。
- git diff --check PASS。本轮不创建提交；旧提交及历史保留。测试以 -B 运行，验证脚本通过 stdin 执行，未创建需清理的测试脚手架。

## 此次修正：全部原算法非空桶（当前有效结果）

2026-11-10 执行。本次仅取消未授权的3账户门槛、其 schema 校验与汇总抑制文案，未新增替代阈值。原有业务门槛与分桶计算保留；本地私有准备副本的 aggregate.py 已同步。未删除文件、未推送、未启用服务、未操作生产；私有仓库权限不足未重试。

真实输入仍为先前保存的2739账户快照、87币名单及同一份 marks，没有重新获取市场行情。对照直接执行固定基线 `bc13b9cf02667f481cb18ffc18dd615e62995c1b:index.html` 的原 `bucketize`，覆盖每个币种、两个方向、全部14档，比较完整桶键集合及每桶名义、仓位数、原图代表价，任何缺桶/多桶或值差异均失败。

复现（输入/输出仅留本地私有准备目录，不加入公开提交）：

```sh
python3 -B verify_real_aggregate.py --snapshot ../hl-liqmap-private-preparation/snapshot.json --marks ../hl-liqmap-private-preparation/marks.json --coins data/coins.json --reviewed-output ../hl-liqmap-private-preparation/aggregate-reviewed.json
python3 -B aggregate.py --validate ../hl-liqmap-private-preparation/aggregate-reviewed.json
python3 -B -m unittest discover -s tests -v
python3 -B verify_browser.py ../hl-liqmap-private-preparation/aggregate-reviewed.json
```

真实全量结果：

```text
accounts 2739; markets 87
upstream_nonempty_buckets 1092; exported_buckets 1092
exact_matches 1092; missing_buckets 0
formerly_suppressed_buckets 459; single_contributor_buckets 256
address_occurrences 0; public_schema PASS
bytes 126090
sha256 dbb4127911f5cdfe3184c54255be9ba31daa7c770592a08cf2ef4b8cad6e217c
upstream_bucketize_sha256 59a9815bb9ed8691153d1beeeeaea47bc459a2880251abb01c1af17e6d50ffc6
```

实际 `aggregate-reviewed.json` 已普通修改为1092桶（旧输出为633桶），并重新读取确认；未删除任何旧验证文件。schema 使用严格字段白名单：无地址、账户列表、稳定账户标识、逐账户权益或逐账户仓位。`positions` 仅为桶内仓位数，接受1仓桶；0仓不是非空桶。7项单元测试 PASS，覆盖单人/两人桶、同人多仓、原账户权益门槛、全部档位与原 JS、私有字段拒绝、mock 发布通道。网络发布测试全部 mock，没有外部发布。

浏览器使用 Alma In-App Browser 直接打开本地 index.html，无启动验证服务。通过页面加载前注入隔离 fetch 与内存 storage，输入是真实完整聚合，市场行情为合成且刻意与固定参考价不同；不读取或发送原始逐账户文件。实际渲染验证覆盖87币、1092条真实桶的数量、代表价、金额和仓位标签，以及各币多空完整汇总；包含256条单仓桶。另验证币种切换、估算开关、70/30滑块、实时行情与固定参考价、503保留旧图与恢复、5类私有字段拒绝、无旧数据请求，全部 PASS。此次未重做 Watchlist 双 dex 流程；旧测试证据留在下方。注入钩子完成后解除。

隐私边界：仅保护完整索引与原始逐账户文件，不保证公开聚合不可推断个别账户。单人贡献桶与价格极值、公开链上关联、跨期差分均允许这种推断；未实施绝对匿名。业务变化仍须披露：真实桶按导出时 reference_mark 固定，最新行情刷新不使其精确动态重分桶；参考行情与快照采集有时差；汇总是有效强平价可定位桶名义，不包含无法定位仓位；旧逐账户视图不在公开聚合内。原有30分钟聚合刷新、缓存及失败保留行为不变。旧 schema 的本地缓存会被拒绝，但不会主动清除，重新加载修正后的聚合即可。

## 旧验证记录——已被此次修正取代（保留原文）

以下633桶及k=3相关结论仅是旧筛选方案的历史证据，不构成原算法全量通过，不能用于当前验收。旧测试/浏览器结果与输出长度也不代表当前版本；当前以本页上方1092桶结果为准。下方的远端状态属于此前核查，此次没有重新查询远端。

2026-11-10 执行；此候选分支尚未推送、部署或启用生产任务。

## 基线与远端核查

- 独立 checkout：`hl-liqmap-privacy-review`；分支 `privacy/aggregate-export`。
- main：`bc13b9cf02667f481cb18ffc18dd615e62995c1b`；snap：`55d471b92d47220f27ae683589efae12c697d0c1`；完成前再次通过 GitHub API 确认未改变。
- GitHub Pages：built，source=main:/。原 harvest 与 snapshot 工作流仍 active；未触发/停止任何任务。
- 原目录 `hl-liqmap` 无 .git，未修改；独立 checkout 四份原 data 文件与 origin/main 逐字节相同，仍被原 Git 历史跟踪。

公开文件核查（不记录真实地址文本）：

| 远端文件 | 字节 | 标准地址模式出现次数 | 结论 |
| --- | ---: | ---: | --- |
| main:data/addresses.json | 6899872 | 78407 | 公开地址池 |
| main:data/accounts.json | 257491 | 3127 | 公开逐账户候选池/账户值 |
| main:data/coins.json | 2897 | 0 | 仅币名及成交额/口径，当前无地址 |
| main:data/volume_cache.json | 9578 | 0 | 仅币名成交额日缓存，当前无地址 |
| snap:data/snapshot.json | 1652614 | 2739 | 公开逐账户权益/仓位快照 |

已检查完整两次最近成功运行日志：snapshot run 42810412880（20281字节）、harvest run 42785632177（21229字节），均0处标准地址模式。只代表这两份日志，不代表全部历史日志无敏感数据。原代码会打印异常响应片段，新代码改成固定错误类别；私有任务仍需按私有日志管理。

## 单元及通道测试（真实终端输出）

命令：`python3 -B -m unittest discover -s tests -v`

```text
test_all_bands_match_original_javascript ... ok
test_collector_requires_private_directory ... ok
test_low_density_counts_unique_accounts_and_does_not_leak_totals ... ok
test_public_schema_rejects_account_records_extra_fields_and_addresses ... ok
test_publication_disabled_before_network ... ok
test_publisher_refuses_existing_branch_with_other_files ... ok
test_publisher_sends_only_validated_aggregate_without_force ... ok
Ran 7 tests in 0.252s
OK
```

发布器测试的网络全部 mock，测试输出中的“published”不代表发生真实外部发布。验证了固定公开仓库、单文件 tree、非强制追加更新、开关关闭时不请求网络、已有目标分支有其他文件时拒绝操作。

Python 全部源码/测试经 AST 语法检查通过；4份工作流经 Ruby YAML 解析通过；init-private.sh 经 sh -n 通过；git diff --check 通过。环境没有 PyYAML/actionlint，未执行 actionlint；YAML解析不等于已通过 GitHub Actions 服务端执行验证。因私有仓库权限阻塞，私有 Actions、secret、token发布权限和实际公网发布未执行。

原 `bucketize` 函数与 origin/main 内容完全相同，SHA256：`59a9815bb9ed8691153d1beeeeaea47bc459a2880251abb01c1af17e6d50ffc6`。测试覆盖14档边界、中段、两方向、空/无效强平、账户门槛、同人多仓、低密度、额外字段、地址及非有限数值拒绝。

## 真实快照算法对照（真实终端输出）

使用 snap 原始2739账户及 main 的87币种名单，私有侧读取当前双 dex 标记价。参考行情与快照时间不同，这是验证用的重分桶，不声称为同一时刻市场状态。实际原始样本、marks 和实际导出只存于工作区私有准备目录，不放公开测试 fixtures 或本次提交。

```text
REAL_EXPORT 2739 private accounts; 633 published buckets; 85496 bytes
ADDRESS_OCCURRENCES 0
UPSTREAM_JS_PARITY 633 buckets matched exactly (notional, position count, representative price)
LOW_DENSITY_AUDIT nonempty 1092 suppressed 459 single_contributor 256 retained_with_gt80pct_single_contributor 171
PUBLIC_SCHEMA PASS
```

85496 是 Python 默认 json.dumps 序列化长度，实际紧凑文件 `aggregate-reviewed.json` 为 **77187 字节**，已用 `wc -c` 实测。比较直接执行 `git show origin/main:index.html` 提取的原 JavaScript，不使用自写替代公式；全部633发布桶美元名义、仓位数、原图代表价精确相同，459个低密度桶在实际输出中不再出现。公开 schema 没有逐账户记录；按独立账户去重的3人规则在私有导出执行，公开验证器只能校验结构，无法从聚合数字独立证明贡献人数。

171个保留桶单人贡献>80%，揭示 k=3 的实际限制；没有优势占比限制、金额量化或差分隐私，不宣称绝对匿名。价格极值及跨期差分仍可用于关联。详见 MIGRATION.md。

## 本地真实浏览器交互

使用 Alma In-App Browser 打开 localhost 验证服务器。服务器只提供前端、校验后的真实聚合 JSON 和合成行情/Watchlist，data/ 等其他路径404，未把真实地址池用于前端 mock。

```json
{
  "checks": [
    "initial render",
    "coin switch and summary",
    "estimate auto-hide and toggle",
    "70/30 slider recalculation",
    "live market and anchored reference",
    "local watchlist dual-dex",
    "503 preserves map and retry recovers",
    "no old data requests"
  ],
  "publicBuckets": 633,
  "requests": 29,
  "result": "PASS"
}
```

第一次测试误选了图例 `.est-l` 而非图表条，修正为 `#longs .est-l` 后上述测试通过；没有为通过测试改变产品计算。

## 私有仓库与未完成项

`gh repo create xyz1367487/hl-liqmap-private --private` 被 token 拒绝：`GraphQL: Resource not accessible by personal access token (createRepository)`。随后读取同名仓库仍404，因此本次没有成功创建远端，也未上传任何数据；404本身不能证明其他凭据下绝无同名私有仓库。

已完成 `hl-liqmap-private-preparation/repository/` 本地准备，包含四份原 main 数据、snap 快照、不可变 seed 快照/marks、纯代码及关闭状态的私有工作流，另有 seed-sha256.json。初始化脚本在可创建仓库的凭据下可执行；遇已有仓库或 .git 会停止并要求核查，不覆盖既有内容。原始日志只留本地 audit，不上传。

GitHub Actions permissions 管理 API 读取返回403，当前账户是否有足够管理/发布权限未验证。仍需：获取创建私有仓库的权限，运行初始化并验证可见性；经人工批准后配置私有任务变量、细粒度发布凭据、验证真实私有运行；审查/合并生产代码、开启聚合发布；最后按 MIGRATION.md 明确清单授权处理已有公开数据。现有公开 main/snap、Pages、原任务、历史和日志仍保持现状。


## 2026-11-11 线上切换完成记录（北京时间）

私有运行 42857496914 已成功完成收割、快照、归档、state 回写与 SSH 聚合发布；私有 state 提交为 75bd2c10f2c56528f5eb60b4c611a66d3ccf561a。公开 aggregate 初次提交 ffc46e6cb522540554f0ef9d1d3d6ba581d063a1 只有 data/aggregate.json；真实输出 87 市场、1108 桶，生成时间 00:55:32，严格 schema 通过，地址模式 0 处。上述数量为该次快照，不是固定值。

公开前端已由 9bcfcf59d7434460f7525f493ffb8db3a9904de2 切换到聚合入口；源码 CI 42859744810、Pages 42859743580 均成功。线上浏览器已读取该新聚合时间，资源记录没有旧 accounts/addresses/snap 请求。两处残留三账户门槛说明已修正为全部非空桶公开；实际导出此前已经无该门槛。本条记录取代前文“前端尚未切换/SSH 发布待验证”的阶段状态。

旧公开 main:data/addresses.json、main:data/accounts.json 和 snap:data/snapshot.json 仍保留，待用户确认具体移除操作；Git 历史未重写。这次切换停止未来公开采集地址，但不代表旧地址数据已经保密。公开聚合不提供绝对匿名保证。
