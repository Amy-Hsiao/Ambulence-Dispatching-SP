# Multi-cut Branch-and-Benders-Cut (B&BC) 執行計畫

前置文件:`L-shaped_implementation_plan.md`(數學推導與分解設計)
本文件:可直接動工的分段執行計畫 — 模組架構、開關設計、Gurobi 參數建議、每段的驗收標準。

**三條鐵律(全程有效)**
1. 不改動 `model_core.py` 的模型邏輯與任何模型參數(成本、容量、懲罰、gap 定義)。
2. 輸出契約不變:console summary 格式、log 位置(`logs\east district stress test`)、
   CSV/Excel 欄位、`compute_vss_evpi()` 介面,全部與 extensive form 完全一致。
3. Extensive form 保持可用:開關切回去就是原本的程式,任何時候都能對照。

---

## 0. 專案目錄重構 + 模組架構與開關設計

### 0.1 目錄重構(Phase R,最先做)

三類檔案、三個資料夾。**只改檔名與呼叫路徑,禁止改動任何核心邏輯。**

```
Taipei Case Test_(06-28)/
├── model core/                      ← 模型核心與共用模組
│   ├── extensive_form_core.py       （原 model_core.py）
│   ├── lshaped_core.py              （新增：oracle / master / 古典迴圈 / B&BC callback）
│   ├── vss_evpi.py                  （原 vss_evpi.py，只搬不改名）
│   ├── config.py                    （資料生成，所有模型共用）
│   └── logging_utils.py             （log 工具，所有入口共用）
│
├── model portal/                    ← 程式入口（模型名稱.py）
│   ├── extensive form.py            （原 sp model.py）
│   ├── deterministic form.py        （原 deterministic model.py）
│   └── benders bbc.py               （新增：multi-cut B&BC 入口）
│
├── run experiment/                  ← 跑實驗的批次程式
│   ├── batch_stress_test.py         （原 run experiment.py）
│   ├── sensitivity_uncertainty.py   （原 run_sensitivity_spatial.py，改名以符現況：三軸）
│   └── scenario_scale.py            （新增，Phase 6：情境規模實驗，見 §2 Phase 6）
│
├── experiment result/               ← 所有實驗結果 Excel/CSV 統一放這裡
│   ├── sensitivity_uncertainty_results.xlsx / .csv   （現有結果搬入）
│   └── scenario_scale_results.xlsx / .csv            （Phase 6 產出）
│
├── data/                            ← 位置不變
├── logs/
│   ├── east district stress test/   ← 既有實驗 log
│   └── scenario scale test/         ← Phase 6 專用 log 子資料夾
└── *.md                             ← 計畫文件
```

（重構時把根目錄現有的結果 CSV/xlsx 一併搬進 `experiment result/`;
各 runner 的輸出路徑常數改指向該資料夾——屬 §0.2 允許的路徑修改。）

**命名的一個硬限制**:會被 `import` 敘述載入的模組,檔名必須是合法 Python
識別字(不能含空格),所以 `model core/` 裡的核心檔一律用**底線**
(`extensive_form_core.py`);入口與批次檔只被直接執行或用 importlib 以路徑載入,
檔名**可以含空格**(`extensive form.py`)。資料夾名含空格沒問題(用 sys.path 加入,
不用套件 dotted import)。

### 0.2 路徑修正清單(重構時唯一允許的程式修改)

| 檔案 | 需要改的路徑 |
|---|---|
| 各入口(`model portal/*.py`) | 開頭加:`PROJECT_ROOT = Path(__file__).resolve().parents[1]`,將 `PROJECT_ROOT/"model core"` 插入 `sys.path`;`import model_core` 改 `import extensive_form_core as model_core`(別名保持下游程式不變) |
| `config.py` | `DATA_DIR = Path("data")`(相對 cwd,搬家後會斷)改為 `Path(__file__).resolve().parents[1] / "data"` |
| `logging_utils.py` | LOG_DIR 同理改為以 `parents[1] / "logs"` 定位,log 仍寫到專案根的 `logs/` |
| `run experiment/*.py` | `ROOT_DIR` 改為 `parents[1]`;`SP_MODEL_PATH` 指向 `model portal/extensive form.py`(或依 `SOLVER_ENGINE` 指向 `benders bbc.py`);`os.chdir(ROOT_DIR)` 維持切到專案根;結果 CSV/xlsx 仍寫在專案根 |

**Phase R 驗收**:重構後跑 `extensive form.py`(S=5),console summary、log 檔名與
位置、VSS/EVPI 數字與重構前**逐字一致**;`sensitivity_uncertainty.py` 能正常分派
並寫出同格式 CSV/Excel。任何一項不一致 = 有邏輯被動到,回退檢查。

### 0.3 新增檔案

```
model core/lshaped_core.py      ← 演算法核心（oracle / master / 古典迴圈 / B&BC callback）
model portal/benders bbc.py     ← 新入口：跑 B&BC 版 RP + VSS/EVPI，輸出格式 100% 比照 extensive form.py
```

### 開關設計(兩種方式並存,擇一使用即可)

**方式 A — 入口點**:`python "model portal/extensive form.py"` = extensive form(原封不動);
`python "model portal/benders bbc.py"` = multi-cut B&BC。互不干擾,最安全。

**方式 B — config 開關**:`config.py` 新增一區(全部是新常數,不動舊常數):

```python
# ── Benders / B&BC 設定 ──────────────────────────────
SOLVER_ENGINE            = "extensive"   # "extensive" | "lshaped"（runner 依此分派）
BENDERS_MULTI_CUT        = True    # False = single-cut（僅供實驗比較，預設恆 True）
BENDERS_ROOT_CUT_ROUNDS  = 15      # root 節點分數解 user cut 輪數（0 = 關閉 root cuts）
BENDERS_USE_USER_CUTS    = True    # True = root 節點分數解 user cut
BENDERS_CUT_VIOL_REL_TOL = 1e-6    # cut 違反判定：Q_s > θ_s + tol·max(1,|Q_s|)
BENDERS_PARALLEL_ORACLES = 1       # 子問題平行數（1 = 循序；Phase 4 才調大）
BENDERS_EV_WARM_START    = True    # 用 EV 一階解當 master 初始 incumbent
```

批次 runner(`run experiment/` 下兩支)依 `SOLVER_ENGINE`
分派到 `extensive form.py` 或 `benders bbc.py`,其餘程式碼零修改。

### `lshaped_core.py` 內部結構

```
class ScenarioOracle          # 每情境一個，整個求解過程只建一次模型
    __init__(instance, s)     #   build_gurobi_model(S=[s], fixed_first_stage=零解)
                              #   → 一階變數 vtype 改 CONTINUOUS（模型變純 LP）
    evaluate(x̄) -> (Q_s, cut) #   更新一階變數 lb=ub → dual simplex 熱啟動重解
                              #   → 讀 ObjVal 與一階變數 reduced cost 組 cut

build_master(instance, S, probs, multi_cut=True)
                              # X/V/U/Y + 一階限制式 + θ_s ≥ 0（multi-cut）
                              # 或單一 Θ ≥ 0（single-cut，比較用）

solve_classic(...)            # Phase 2：古典迭代（master 解到底↔加 cut），
                              #   兼作除錯工具與 B&BC 的對照基準
solve_bbc(...)                # Phase 3：單一 master + lazy callback（正式引擎）
solve(...)                    # 對外唯一入口，回傳統一 result dict（見 §5）
```

---

## 1. Gurobi 參數建議(B&BC 核心)

### Master(B&BC 模式)

| 參數 | 建議值 | 理由 |
|---|---|---|
| `LazyConstraints` | **1(必設)** | 沒設 `cbLazy` 直接報錯;設了 Gurobi 會自動停用與 lazy 不相容的 dual reduction/對稱性化簡,保證正確性 |
| `PreCrush` | **1** | user cut(`cbCut`)必需——讓 cut 能映射回 presolve 後的模型;先設起來無害,Phase 4 開 user cut 時不用再動 |
| `MIPFocus` | **1** | 每個新 incumbent 都會觸發一輪 cut 生成,前期多找可行解 = cut pool 長得快 |
| `Threads` | 0(預設) | master 極小(~200 變數),B&B 本身不是瓶頸;留全核給子問題平行 |
| `NumericFocus` | **1** | 懲罰係數 1e5 量級,cut 係數(reduced cost)同量級,防數值漂移 |
| `TimeLimit` / `MIPGap` | 沿用 config 的 3600 / 0.01 | 輸出契約:gap 與時限語意跟 extensive form 一致 |
| `Heuristics` / `Cuts` | 預設 | master 太小,調了沒差;不要畫蛇添足 |

### Callback 規則

```
where == MIPSOL（整數 incumbent，正確性所在——必須做）:
    x̄ = cbGetSolution(X,V,U,Y)，四捨五入到整數（防 1e-6 級噪音進 oracle）
    對每個 s：Q_s, cut = oracle[s].evaluate(x̄)
    若 Q_s > θ̄_s + BENDERS_CUT_VIOL_REL_TOL·max(1,|Q_s|)：cbLazy(cut)
    （multi-cut：一次最多加 S 條；全部檢查完才 return，不要提早跳出）

where == MIPNODE 且 MIPNODE_STATUS == OPTIMAL（user cut，Phase 4 選配）:
    僅在 root（cbGet(MIPNODE_NODCNT) == 0）且輪數 < 上限（建議 20）時：
    x̄ = cbGetNodeRel(...)（分數解——cut 推導對任意 x̄ 有效，分數點照樣合法）
    違反者 cbCut(cut)
    節點深處不加：每個 node LP 都跑 S 次 oracle 會把樹搜尋拖死
```

**Lazy vs user cut 的分工**:lazy(`cbLazy`)是**正確性**——沒有它,整數解可能低估
θ_s 而被誤認為最優;user cut(`cbCut`)是**加速**——在 root 的分數解上先把下界
抬高、減少節點數。所以 lazy 從 Phase 3 第一天就有、不可關;user cut 是 Phase 4
的選配開關,預設關,實測 root gap 收斂變快才留著。

### 子問題 Oracle(每情境的 LP)

| 參數 | 建議值 | 理由 |
|---|---|---|
| `Method` | **1(dual simplex)** | 只改變數 bounds 時 dual simplex 從上一組基熱啟動,重解通常一秒內;barrier 每次從頭來,反而慢 |
| `OutputFlag` | 0 | 子問題靜默，log 只留 master 進度 |
| `Threads` | **1** | 單情境 LP 不大,單執行緒最穩;平行化留給「同時解多個 oracle」（process/thread 層），避免 oversubscription |
| `NumericFocus` | 1 | 同 master |

---

## 2. 分段執行(每段獨立可驗收,做完一段就能停)

### Phase R — 目錄重構(半天,§0.1–0.2)
搬檔、改名、修路徑,零邏輯改動。
**驗收**:§0.2 表列——重構前後 extensive form 輸出逐字一致。

### Phase 0 — 骨架與開關(半天)
建 `lshaped_core.py` 空殼 + `benders bbc.py` 入口 + config 新增 §0 的開關區。
`benders bbc.py` 先直接轉呼叫 extensive form(passthrough)。
**驗收**:兩個入口跑 S=5 輸出逐行一致(diff log 檔);runner 依 `SOLVER_ENGINE` 正確分派。

### Phase 1 — ScenarioOracle(2–3 天)
實作 oracle:單情境 LP 建置、一階 vtype 鬆弛、bounds 更新、RC 讀取、cut 組裝。
**驗收(V1)**:任取一階可行解 x̄,`oracle.evaluate(x̄)` 的 Q_s 與「extensive form 固定
x̄ 後單情境求解」目標值相對誤差 < 1e-6;cut 在 x̄ 處取等式(θ_s = Q_s);
S=1 時 master(無 cut, θ 換成直接嵌入)≡ 原確定性模型。

### Phase 2 — Master + 古典 multi-cut 迴圈(2–3 天)
`build_master` + `solve_classic`:master 解到底 → oracle → 加 cut → 重解,直到
UB−LB ≤ gap 或時限。每輪列印 iter / LB / UB / #cuts(除錯的生命線)。
**驗收(V2)**:S=5 Both[0.8,1.2] 收斂到與 extensive 解 25,426,150.72 相差 <(兩邊 gap 和);
LB 逐輪單調不減;一階解 CCP 集合一致;WS ≤ RP ≤ EEV 無警告。
*此段程式碼不是拋棄式——作為 Phase 3 B&BC 的 correctness baseline。*

### Phase 3 — B&BC(lazy callback)(2–3 天)
`solve_bbc`:§1 的參數 + MIPSOL callback;`BENDERS_ROOT_CUT_ROUNDS` 輪 root MIPNODE user cut
(在 root LP 鬆弛解上以 `cbCut` 墊 cut pool);`BENDERS_EV_WARM_START` 把 EV 一階解 +
θ_s = Q_s(x_EV) 餵給 master 當初始 incumbent。
**驗收(V3)**:與 Phase 2 古典迴圈同一實例的最終目標值一致(容差 = gap);
S=5 Both[0.5,1.5](extensive 過夜磨出的參考值)對得上;
記錄並列印 cuts_added / oracle_solves / callback 時間占比。

### Phase 4 — 加速(選配,依實測需要)(3–5 天)
依序、一次只開一個、每個都留開關:
(a) `BENDERS_PARALLEL_ORACLES > 1`:callback 內以 ThreadPool 同時解多個 oracle
    (每個 oracle 各自的 `gp.Env`,Threads=1)——這是把你 24 個邏輯核心用滿的正解;
(b) `BENDERS_USE_USER_CUTS = True`:root 分數解 user cut(§1 規則);
(c) single-cut 模式跑一次對照(論文可報 multi-cut vs single-cut 迭代數比較)。
**驗收**:每項開啟後,同實例牆鐘時間下降且目標值不變;S=5 全設定 wall time 基準表。

### Phase 5 — runner 整合(1 天)
既有兩支 runner 接上 `SOLVER_ENGINE` 分派;輸出路徑改指 `experiment result/`。
**驗收**:`sensitivity_uncertainty.py` 以兩種引擎各跑一組,CSV/Excel 格式一致。

### Phase 6 — 情境規模實驗程式 `run experiment/scenario_scale.py`(1–2 天)
B&BC 與 multi-cut 全部完工並通過 V1–V3 後才執行。規格:

**實驗設計**
- 固定所有現行參數(定案基礎設定:全局 [0.8,1.2] + 空間 U[0.5,1.5] 正規化、seed 42)、T=8;
- `S_VALUES = [5, 20, 30, 50, 100, 150]`,依序執行,每個 S 解 RP + VSS/EVPI;
- 引擎依 `SOLVER_ENGINE`(此實驗預設 `"lshaped"`;選配:S ≤ 30 同時跑 extensive 做演算法對照表);
- **早停規則:某個 S 的 Final Gap > 10% → 該列標 STOP,後續更大的 S 全部跳過**
  (沿用 `batch_stress_test.py` 既有的 GAP_STOP_PCT 機制);
- 免費的好性質:`stable_seed` 以情境 ID 命名亂數流,S=20 的前 5 個情境與 S=5 完全相同
  (common random numbers),不同 S 之間的 VSS 變化是收斂效應、不是換樣本的雜訊,論文可直接寫。

**輸出**
- log:每個 S 一個檔,自動移入 `logs/scenario scale test/`;
- 結果:`experiment result/scenario_scale_results.xlsx` + 同名 CSV(來源真相),
  每解完一個 S 立即寫檔;
- Excel 欄位與現行 18 欄完全相同(factor | |I| Disaster | |J| CCP | |H| Hosp | |S| Scen |
  |T| Per | obj_value | First Stage Decision | Best LB | Best UB | CPU Time(s) | num_vars |
  num_constrs | Nodes | Iteration | Final Gap(%) | VSS(%) | EVPI(%)),
  factor 欄填 `Scenario x5`、`Scenario x20`⋯(比照論文表格列名)。

**必須先想清楚的一個成本**:VSS/EVPI 的 WS 要對每個情境各解一次
(每個上限 120 秒),S=150 時光 WS 最壞就是 5 小時。因此 runner 提供
`VSS_EVPI_MAX_S`(預設 50):S 超過此值時 VSS%/EVPI% 填 NA、只解 RP;
若大 S 也要 VSS,先做 Phase 4(a) 的平行 oracle,把 WS 平行化後再開。

**驗收**:S=5 的結果與 Phase 3 驗證值一致;早停規則以人工調低 GAP_STOP 觸發測試;
Excel 表頭逐字比對;log 進入正確子資料夾。
**產出**:論文情境規模章節主表 + |S| × {extensive, B&BC} CPU 對照表(演算法章節)。

---

## 3. 輸出一致性契約(Phase 0 就凍結)

`solve(...)` 回傳的 result 必須讓 `benders bbc.py` 印出與 `extensive form.py`
**同格式**的 summary,並讓 runner 的 CSV/Excel 欄位照填:

| 欄位 | L-shaped 下的定義 |
|---|---|
| obj_value / Best UB | master incumbent 的完整目標值(一階成本 + Σ p_s Q_s,以 oracle 重評,**不是** θ 值——θ 可能低估) |
| Best LB | master `ObjBound` |
| Final Gap(%) | (UB−LB)/UB,與 extensive 語意相同 |
| CPU Time(s) | solve() 全程牆鐘(含 root user cuts 與 oracle) |
| num_vars / num_constrs | master 值(另於 log 註明 oracle 合計,CSV 不加欄) |
| Nodes / Iteration | master `NodeCount` / `IterCount` |
| First Stage Decision | 同現有格式(CCP Jxx -> X: 1, Staff(V): ...) |
| VSS(%) / EVPI(%) | `compute_vss_evpi()` 原樣呼叫——它只吃 rp_lb/rp_ub/rp_gap 三個數字,引擎無關 |

**UB 一定要用 oracle 重評的真實成本**,不能拿 master 目標值直接當 UB——lazy cut
未加齊前 θ_s 會低估,這是 B&BC 實作最常見的正確性 bug,列為 code review 必查項。

---

## 4. 風險清單(對應 code review 檢查點)

1. **θ 低估被當 UB** → §3 的重評規則,V2/V3 驗收會抓到。
2. **MIPSOL 的 x̄ 帶浮點噪音**(X=0.9999997)→ 進 oracle 前 round;V/U/Y 同。
3. **重複 cut 灌爆 master** → 違反容差用相對值;同一 x̄ 重複出現時跳過(dict 記 x̄ hash)。
4. **LazyConstraints 忘記設** → Gurobi 直接 error,Phase 3 第一次跑就會發現。
5. **user cut 在深層節點觸發** → callback 內 NodeCount==0 防呆(Phase 4)。
6. **平行 oracle 共用 Env 崩潰** → 每 oracle 獨立 `gp.Env`(Phase 4a 規格)。
7. **root user cut 輪數失控** → 以 `BENDERS_ROOT_CUT_ROUNDS` 限制 root 節點 `cbCut` 次數;深層節點不加 user cut。

---

## 5. 之後的 MCVaR / DRO(不現在做,但架構已預留)

`ScenarioOracle` 完全不變;只有 master 的 θ 聚合改變(CVaR:加 η 與 z_s ≥ Σp·θ 結構;
DRO:worst-case 權重 / column-and-constraint generation)。`solve()` 的 result 契約
不變,下游 runner / VSS 工具全部沿用。

---

**建議動工順序:Phase R 先做並驗收(輸出逐字一致),再 Phase 0 + Phase 1 一起做(骨架小,oracle 是重點),V1 過了再往下。**
