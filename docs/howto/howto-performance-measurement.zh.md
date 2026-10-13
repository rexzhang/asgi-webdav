# 性能测量与兼容性验证指南（GIL / FT / FT+JIT）

本项目附带一套测量工具（`tools/perf`，入口 `python -m tools.perf`），用于检查两个方向的问题：

1. 不同解释器的兼容性：GIL/FT(free-threaded)/FT+JIT
2. 性能优化参考：热点在哪里、哪些优化方向值得投入。

工具优先使用 Python 3.15 引入的机制：`profiling.sampling`（Tachyon 采样剖析器，PEP 799，唯一支持 FT 构建的采样器）、实验性 JIT（PEP 744/836）、默认帧指针（PEP 831，利好 Linux perf）。Windows 不在测量范围内。

## 1. 环境模型

| 环境                  | 目标               |
| --------------------- | ------------------ |
| macOS                 | 日常开发快速检测   |
| Linux（lima VM 载体） | 类生产环境完整检测 |

- lima 能否替代 macOS：出最终测量数字可以（Linux 无采样权限摩擦、与未来 CI 口径一致）；日常诊断迭代不建议（开发热循环每次进 VM 摩擦大，且 guest 与宿主争抢资源）。
- 代表性缺口：lima 是 Debian glibc + virtio 磁盘，生产镜像是 Alpine musl——lima 的绝对值是"Linux-glibc-VM 风味"；需要生产风味绝对值时，用生产 Docker 镜像在 Linux 上测。热点分布跨 OS 稳定，相对结论可迁移。
- lima VM 内测量时 fixtures 拷入 VM 本地磁盘（不走共享挂载），VM CPU/内存配额固定。

## 2. 解释器矩阵

滚动版本窗口：始终只覆盖最新的两个 Python 版本（当前 3.14 + 3.15），随项目年度升级滚动。

| flavor                     | 标签        | macOS 来源                    | lima 来源                                                 |
| -------------------------- | ----------- | ----------------------------- | --------------------------------------------------------- |
| GIL 3.14（滚动第二版本）   | `py314`     | `.venv314/bin/python`         | 不默认构建                                                |
| GIL 3.15                   | `py315`     | `.venv/bin/python`            | 源码构建                                                  |
| FT 3.15（`--disable-gil`） | `py315t`    | 暂缺（brew 无 FT 构建，跳过） | 源码构建                                                  |
| FT+JIT 3.15                | `py315tjit` | 不构建                        | 源码构建（`--disable-gil --enable-experimental-jit=yes`） |

- JIT 活性检测：对目标解释器检查 `sys._jit.is_enabled()`（3.15+），结果记入 `meta.json`。
- FT 下 uvloop/httptools 可能无 wheel：安装走三级递进（wheel → 源码编译 → 跳过，回退 asyncio）；`compat` 会记录实际事件循环（解析 uvicorn banner），跨 flavor 对比时注意 loop 口径。
- pytest 在 FT venv 下用 `-o addopts=` 剥离 `--cov`（coverage 的 C 扩展可能不可用）。

## 3. 工具使用

```bash
# 前置检查（解释器矩阵 / oha / lima / Tachyon 权限）
.venv/bin/python -m tools.perf preflight

# 生成固定数据（4k.bin / 64m.bin / put-4k.bin / dir-{10,100,1000}）
.venv/bin/python -m tools.perf fixtures

# 兼容性：pytest 全套 + 冒烟负载 + 环境采集
.venv/bin/python -m tools.perf compat -p py315

# 吞吐矩阵（默认 9 个 workload × 并发 1/4/16 × 5 重复）
.venv/bin/python -m tools.perf bench -p py315 -p py314
.venv/bin/python -m tools.perf bench --quick            # 冒烟
.venv/bin/python -m tools.perf bench --stall            # + asyncio 阻塞检测

# 采样剖析（Tachyon run 模式，输出 collapsed/flamegraph/pstats）
.venv/bin/python -m tools.perf profile -p py315 -w propfind-1-1000 --mode wall

# 微基准 / 进程内基准
.venv/bin/python -m tools.perf micro -p py315 -p py314
.venv/bin/python -m tools.perf inproc -p py315 --requests 1000

# 两次 run 对比（可作未来 CI 门禁）
.venv/bin/python -m tools.perf compare output/perf/run-A output/perf/run-B

# 基线管理（详见 §4 经典用例）
.venv/bin/python -m tools.perf baseline list                                    # / save / promote / show / remove / plot
.venv/bin/python -m tools.perf baseline save output/perf/run-A --name pre-opt   # 手动命名保存
.venv/bin/python -m tools.perf baseline promote output/perf/run-A               # 保存进代码库
.venv/bin/python -m tools.perf compare --baseline pre-opt output/perf/run-B --output report.md

# 一键 macOS 战役（compat → bench → micro → inproc → profile）
.venv/bin/python -m tools.perf run

# Linux 腿（lima VM：自动创建、源码构建三个解释器、跑完整矩阵）
.venv/bin/python -m tools.perf vm create
.venv/bin/python -m tools.perf vm sync-repo
.venv/bin/python -m tools.perf vm setup        # ~30-60 分钟（源码构建）
.venv/bin/python -m tools.perf vm compat
.venv/bin/python -m tools.perf vm bench
.venv/bin/python -m tools.perf vm perf         # perf record + PYTHONPERFSUPPORT=1（产物自动取回宿主 output/perf/vm-perf-*/）
```

`vm compat` / `vm bench` 的结果经 `limactl cp` 取回并入同一 run 目录（标签带 `-lima` 后缀），`--run-dir` 可把多腿结果合并到一次 run。

### `TOOLS_PERF_*` 环境变量（repo 根 `.env` > 进程环境 > 默认值）

| 变量                                                      | 默认                                                 | 说明                                   |
| --------------------------------------------------------- | ---------------------------------------------------- | -------------------------------------- |
| `TOOLS_PERF_PYTHON_314 / 315 / 315T`                      | `.venv314/bin/python`、`.venv/bin/python`、空        | 解释器路径，空=跳过该腿                |
| `TOOLS_PERF_LOADGEN`                                      | `auto`                                               | `oha`（brew 安装）或内置纯 stdlib 驱动 |
| `TOOLS_PERF_DURATION / REPEATS / WARMUP`                  | `10 / 5 / 1`                                         | 统计参数                               |
| `TOOLS_PERF_CONCURRENCIES`                                | `1,4,16`                                             | 并发档位                               |
| `TOOLS_PERF_COOLDOWN`                                     | `2.0`                                                | 组合间隔秒                             |
| `TOOLS_PERF_FIXTURES_DIR / LOG_DIR`                       | `output/perf/fixtures`、`output/perf`                | 目录                                   |
| `TOOLS_PERF_SAMPLING_RATE / PROFILE_DURATION`             | `10khz / 20`                                         | profile 参数                           |
| `TOOLS_PERF_VM_NAME / VM_TEMPLATE / VM_DISK / APT_MIRROR` | `asgi-webdav-tools-d13`、`template:debian`、`40`、空 | lima VM                                |

## 4. 经典用例

### 4.1 基线比对：回归检测 / 优化收益

改动代码后，把新测量结果与既有基线比对，判定回归或量化优化收益。两种对照源：

场景 A——对照库内基线（`tools/perf/baselines/current/`，随代码提交），适合改动后回归检测：

```bash
.venv/bin/python -m tools.perf run                                   # 完整战役，结束时自动另存 output 基线
.venv/bin/python -m tools.perf compare output/perf/run-<时间戳> --fail-threshold 15
```

`compare` 单参数即对照库内 `current`；超过阈值的回归以非零码退出（CI 门禁预留）。

场景 B——对照本地命名基线，适合量化某次优化的前后收益：

```bash
.venv/bin/python -m tools.perf bench                                 # 优化前
.venv/bin/python -m tools.perf baseline save output/perf/run-<时间戳> --name pre-opt
# ……实施优化……
.venv/bin/python -m tools.perf bench                                 # 优化后
.venv/bin/python -m tools.perf compare --baseline pre-opt output/perf/run-<时间戳> --output report.md
```

比对报告头部展示双方的版本与 git 标识（每次 run 的 `meta.json` 自动携带 `project` 字段），报告自包含，可归档或贴进 PR；markdown 报告含逐组合 verdict（improved/regressed/flat，按指标方向判定：rps 越高越好，p99/cpu 越低越好）。

### 4.2 将当前基线保存进代码库

`tools/perf/baselines/current/` 是随代码库提交的滚动单份基线：开发改动或年度依赖/解释器升级后，在同一台机器上重跑矩阵做回归对照；历史即 git 历史（`git log -- tools/perf/baselines` 可回查任意时点）。

```bash
.venv/bin/python -m tools.perf baseline promote output/perf/run-<时间戳>
git diff tools/perf/baselines/current                                # 审阅数值变化
git add tools/perf/baselines && git commit                           # 提交
```

- 前提：git 工作树干净（脏树拒绝 promote——防止覆盖未提交的上次快照、防止基线无法钉定到 commit；`--force` 可越过）。
- 只进测量数据，且全部按排序键规范化重写（两次 promote 间 diff 只含真实数值变化）；server 日志、渲染产物（`summary.md` 等）一律排除。
- 每次 promote 整体覆盖 `current`（滚动策略，正常路径无需 `--force`）。
- 与 4.1 场景 A 构成库内基线的生命周期：检测 → 对照 → 无回归 → promote 更新。

### 4.3 热点剖析

```bash
.venv/bin/python -m tools.perf profile -p py315 -w propfind-1-1000 --mode wall
```

Tachyon run 模式把被测服务器拉起为子进程，规避 macOS 对 attach 的 `task_for_pid` 权限限制；若仍被拒，火焰图改在 lima 出（`vm perf`），Linux 无此问题。

### 4.4 FT 解释器兼容性检查

```bash
.venv/bin/python -m tools.perf vm setup        # 首次：源码构建三个解释器，~30-60 分钟
.venv/bin/python -m tools.perf vm compat       # pytest 全套 + 冒烟负载 + 环境采集
```

macOS 上 brew 无 FT 构建且 FT+JIT 不构建，FT/FT+JIT 两腿只在 lima VM 内检查。

### 4.5 性能趋势回看

```bash
.venv/bin/python -m tools.perf baseline plot                    # 默认 rps，输出 html+svg+md 三件套
.venv/bin/python -m tools.perf baseline plot --metric p99 -w get-4k -w propfind-1-1000 -c 16
```

把所有已存基线（output 库）串成时间序列折线（x=基线按保存时间排序，每解释器×并发一条线，缺失点断线）：`trend-*.html` 交互查看、`trend-*.svg` 矢量图片（可嵌 README/PR）、`trend-*.md` 数值矩阵（含 vs first 比率）。零绘图依赖（纯 stdlib SVG）。

## 5. 兼容性判定标准（`compat`）

每个 flavor 一行结论（`compat/summary.md`）：

1. pytest 全套通过（在目标解释器下子进程运行）；
2. 冒烟负载零错误：OPTIONS / GET / PUT / PROPFIND 各 ~5s、并发 4，外加 FT 并发写压力（同路径多 PUT）；
3. 环境采集：`sysconfig Py_GIL_DISABLED`、`sys._is_gil_enabled()`（FT 构建下必须为 False，否则标记"FT 构建无效"）、uvicorn 实际事件循环、启动期依赖可用性（aiofiles/uvloop/httptools/profiling.sampling）。

## 6. 剖析输出解读

- `profile` 子命令使用 Tachyon run 模式（见 4.3）。
- 输出：`collapsed.txt`（可导入 speedscope）、`flamegraph.html`、`pstats.txt`、`profile.bin`（可用 `python -m profiling.sampling replay` 事后转任意格式）。
- 关注：`<GC>` 帧（GC 开销）、`--async-aware` 的任务栈重建、`--native` 的 C 扩展帧；`--opcodes` 可看自适应解释器特化。
- Linux 腿另有 `vm perf`：`perf record -g` + `PYTHONPERFSUPPORT=1`（3.15 默认帧指针使原生栈回溯可靠），输出 `perf.script`。

## 7. baseline 与 compare 机制

- 基线自动保存：`run` 与 `vm bench` 结束时自动把该时刻的 run 目录快照存为基线，命名规则为 `时间-短githash`（如 `20261011-162148-3b150a7`）；`baseline save --name` 可手动命名。
- output 库基线只存轻量 JSON/md 工件（不含 raw 采样），完整数据保留在原 run 目录；`baseline save` 重名需 `--force`。
- 名字解析 repo 优先：`compare --baseline current` 与 `baseline show current` 都指向库内基线，output 库同名条目被遮蔽（`baseline list` 以 origin 列区分两者）。
- `baseline remove` 拒绝库内基线（删除是 git 操作）；`baseline plot` 趋势只统计 output 库（库内 current 本是某条 output 基线的副本，重复计点无意义）。
- `compare` 按（interpreter, variant, workload, concurrency）四元组对齐；比对报告默认写入新一侧 run 目录（`compare-report.md` + `.json`），`--output` 可指定路径；`--fail-threshold` 超阈值以非零码退出。

## 8. 指标与解读口径

- 指标：RPS（吞吐）、p99 延迟、cpu_per_req（服务器每请求 CPU 秒，由 `ps` 读取子进程 CPU 时间差得出）。
- 统计：每个组合先跑 1 次预热（丢弃），再跑 N 次重复（默认 5），取 median；MAD/median > 5% 在 summary 标记 `unstable`；组合之间强制 cooldown（默认 2s）。
- 解读规则：
    - 以 median 为准；`unstable` 标记的样本不要用来下结论（增大 repeat 重测）。
    - `server cpu/sample` 是服务器子进程在该组合全部重复中的 CPU 时间均值——乘以请求数可得 cpu_per_req。
    - 负载器类型（oha vs stdlib driver）记录在每个样本里；跨解释器对比必须同一负载器。
    - FT 构建若回退 asyncio loop，与 uvloop 数字不可直接对比；对比前先对齐（在 FT venv 卸载 uvloop）。
    - run 目录 `summary.json` 带 `schema_version`。
    - 比对结论只在同机、同负载、同机器状态下有效。

## 9. 代码库中基线环境

- Macbook Air M4(4P6E)
