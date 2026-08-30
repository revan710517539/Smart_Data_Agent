# 定时任务 Tab 系统风格收敛 QA

- source visual truth: `<temporary-input>/schedule-tab-reference.png`
- implementation screenshot: `<workspace>/schedule-tab-system-refined.png`
- calendar screenshot: `<workspace>/schedule-tab-calendar-refined.png`
- combined comparison: `<workspace>/schedule-tab-reference-comparison.png`
- browser: Codex in-app Browser，SDA 本地开发地址 `${SDA_WEB_ORIGIN}`
- viewport evidence: 浏览器截图为 1280×720；用户截图为 2302×934，组合图将用户截图按宽度归一到 1280px 后与实现截图纵向拼接
- state: 华兴银行 / 站内数据 / 自营双周报放款与资产表现_2026-08-25 / 定时任务 / 每日 / today 为取值日前第 7 日

## Full-view comparison

组合图上半部为用户标注截图，下半部为本次实现。实现继续使用 SDA 现有的白底、细灰边框、8px 圆角、低饱和绿色和紧凑桌面字体；信息层级从冗余说明改为“SQL 配置 → SQL 时间参数 → 操作”。

- 已删除机构/别名/CSV 文件说明行，定时任务内容直接从关联 SQL 开始。
- 已删除 SQL 参数辅助说明、N 日预览提示和底部操作说明。
- 只保留 SQL 时间参数上方一条横向分隔线；浏览器按全宽 `.border-t` 实测仅 1 条。
- 关联 SQL、循环方式、执行日期与时间保持同一行；循环方式控件实测字体 12px、高度 36px。
- 取值方式与 N 日输入框实测 y 坐标均为 469px、高度均为 36px，标签基线和控件顶边一致。

## Focused interaction comparison

- 取值方式使用项目现有 Radix Select，菜单为白底、细灰边框、8px 圆角、绿色选中态，选项仅固定值、取值日、取值日前第 N 日。
- N 日输入改为无浏览器数字微调器的文本数字输入，填写 7 后不再出现预览提示。
- 执行日期与时间使用项目 Calendar、Popover、Select 组合；日历显示中文月份和中文星期，日期、小时、分钟均可选。
- 日历压缩为 28px 日期单元，720px 高桌面视口中日期和时间选择器完整可见，无裁切。
- 浏览器控制台无 warning/error。

## Deterministic measurements

- 关联 SQL、循环方式、执行日期与时间控件高度均为 36px。
- 循环方式、执行日期与时间、取值方式、N 输入字体均为 12px。
- 取值方式：x=554、y=469、w=299、h=36。
- N 输入：x=865、y=469、w=328、h=36。
- 已确认页面中不存在：`打开仅加载配置`、`按 SQL 参数类型选择`、`测试只校验连接与参数`、`预览：`。

## Comparison history

- iteration 1：已完成日期时间、N 日模式和测试按钮，但用户指出字体偏大、说明文字冗余、横线过多、N 日错位及原生日历风格不统一。
- iteration 2：删除四处冗余信息，统一 36px/12px 控件规范，改用系统 Select/Popover/Calendar，完成中文日历与 N 日对齐。
- iteration 2 focused fix：发现 720px 视口中时间选择器位于截图下沿，进一步压缩日历行距和日期单元后，日期与时间完整可见。

## Verification

- [x] `npm run typecheck`
- [x] `npm run build`
- [x] `npm run test:frontend-size`
- [x] Codex in-app Browser 真实交互：定时任务 Tab、取值方式下拉、N 日输入、日期时间弹窗
- [x] 组合截图对比与局部弹窗复核
- [x] 浏览器控制台无 warning/error

final result: passed

---

# Design QA — 可视化报表页头与模板提示收紧

- source visual truth: `/var/folders/5j/1tdj8bb17jbc5z_08kq65_bc0000gn/T/codex-clipboard-ce4eca88-d67f-412a-8651-6f1d56cd107b.png`, `/var/folders/5j/1tdj8bb17jbc5z_08kq65_bc0000gn/T/codex-clipboard-ffaff0be-c0cf-4fc1-9480-ee5f0153841d.png`
- reproduced pre-change screenshot: `output/playwright/visual-report-header-notice-cleanup-20260830/before.png`
- iteration-2 screenshots: `output/playwright/visual-report-header-notice-cleanup-20260830/after-header.png`, `output/playwright/visual-report-header-notice-cleanup-20260830/after-template.png`
- same-input comparison: `output/playwright/visual-report-header-notice-cleanup-20260830/comparison.png`
- viewport: 1470×750 CSS px; both local captures are 1470×750 and the side-by-side comparison is 2940×750 without density resampling
- state: 华兴银行 / 可视化报表 / 创建订单漏斗转化_2026-08-27 / 编辑态 / 银行经营排名模板

## Findings

- No actionable P0/P1/P2 difference remains. The standalone text return row is gone; the compact return icon now precedes the report title on the first title baseline.
- Removing the standalone row, title description, institution metadata and save-success banner moves the complete report page upward while retaining the shared `StandardAnalysisPageHeader` gutter, action alignment and typography.
- The return control uses the existing Lucide `ArrowLeft` asset at 14px inside a 24px button, with an accessible name, tooltip, hover treatment and keyboard focus ring.
- Save, destination and template-application success banners no longer reserve vertical space. Genuine save errors, template field-mapping warnings and freeze restrictions remain visible through their existing alert paths.
- Applying `银行经营排名` still produces three ranking columns and 24 progress cells in the authenticated fixture; the table data, navy header, banded rows and progress bars remain unchanged.

## Interaction evidence

- Clicking 保存 completed without rendering `可视化报表已保存。`; the existing save request and `正在保存…` transient state remain intact.
- Clicking the title-side `返回报表首页` control returned to the existing landing list with `最近创建` and `新建报表`, then the same report reopened normally. The final source contract fixes this control before `data-visual-report-title` and removes both description strings.
- Applying the featured custom template produced nine `-排名` text occurrences across headers/accessibility output and 24 progress cells, with no `已应用自定义模板` or generic template-success banner.
- The in-app Browser reached the local login page but had no authenticated session, so final same-state acceptance used the already authenticated Chrome SDA tab; no credential was copied or changed.

## Comparison history

- iteration 1: captured the existing standalone return row and save-success banner in the authenticated historical report.
- iteration 2: moved the icon into the title, removed success-only banners, reran save/template/back interactions and compared the same report at the same viewport.
- iteration 3: applied the user's follow-up by moving the icon from the title's right side to its left and removing the two remaining title-detail rows. The focused source contract, typecheck and build pass; the latest supplied screenshot path was already unavailable, and the Chrome extension disconnected before a new authenticated capture, so the prior screenshots are retained as iteration evidence rather than mislabeled as the final micro-adjustment.

## Verification

- [x] `node scripts/visual-report-workbench-contract.mjs`
- [x] `node scripts/visualization-interaction-contract.mjs`
- [x] `npm run typecheck`
- [x] `npm run build` (3530 modules, 82 precompressed assets)
- [x] authenticated Chrome save, template and return journey
- [x] authenticated browser console error count: 0
- [x] local frontend 5174 HTTP 200 and `GET /api/ready` ready=true with database ready

final result: passed

---

# Design QA — 可视化报表数据重绑与页头操作区

- source visual truth: `/var/folders/5j/1tdj8bb17jbc5z_08kq65_bc0000gn/T/codex-clipboard-fc099235-ca18-4e7f-bee0-8843d1792b66.png`
- reproduced pre-fix screenshot: `output/playwright/visual-report-schema-header-before.png`
- implementation screenshot: `output/playwright/visual-report-schema-header-after.png`
- same-input comparison: `output/playwright/visual-report-schema-header-comparison.png`
- viewport: 1470×750 CSS px, device scale factor 2
- pixel dimensions: both browser captures are 1470×750 px from the same Chrome viewport and authenticated report state; the comparison is 2940×750 px with no density resampling
- state: 华兴银行 / 可视化报表 / 标品双周会周度sql_2026-08-14 / 编辑态 / 保存结果

## Findings

- No actionable P0/P1/P2 difference remains. The three destination actions now occupy the existing standard page-header action group, immediately before 便签、编辑/保存、留言板.
- Fonts and typography: all six actions retain the existing 12px desktop control typography, icon scale and single-line labels; the title and metadata hierarchy are unchanged.
- Spacing and layout rhythm: the action group is 518.66×36px at x=928.66 and shares the header's y=42.62 baseline. The header ends at x=1447.33 within a 1470px viewport, and body scroll width equals document client width, so no horizontal overflow is introduced.
- Colors and visual tokens: completed destination state keeps the existing pale-green semantic treatment; the successful save banner uses the existing green status token instead of the previous red error token.
- Image quality and asset fidelity: the page uses the existing Lucide icon set and rendered chart; no source imagery or raster asset was replaced.
- Copy and content: the false `可视化报表引用的数据结构已变化` alert is absent after save, and the visible status is `可视化报表已保存。`.

## Full-view and focused comparison evidence

- The left side of the combined image reproduces the original defect at the same browser viewport: red schema alert and a detached second-row destination toolbar.
- The right side shows the same report after repair: one upper-right action row, no detached toolbar, no red alert, and the chart remains visually and functionally unchanged.
- A separate focused crop was not needed because the complete header, status banner and chart are legible together in the 2940×750 comparison.

## Interaction and runtime evidence

- Opened the historical report from the real report list, clicked 保存, waited for the API result, and observed `可视化报表已保存。`.
- The persisted dataset reference was rebound from the retired 2026-08-14 delivery to the current 2026-05-06 delivery while retaining all 14 physical field codes.
- DOM readback found zero alerts, a single success status, and no page overflow.
- Browser console contained no error entries. Existing transient Recharts zero-size warnings were observed during route transitions and are unrelated to this header/schema repair.

## Comparison history

- iteration 1: reproduced the red fingerprint alert and detached destination toolbar in the authenticated historical report.
- iteration 2: aligned frontend/backend compatibility to physical field label and type family, moved destination actions into `StandardAnalysisPageHeader`, reloaded the same report, saved successfully, and captured the post-fix comparison. No P0/P1/P2 visual issue remained.

## Verification

- [x] `python3 -m unittest backend.platform.tests.test_visual_reports` (17 tests)
- [x] `node scripts/visual-report-workbench-contract.mjs`
- [x] `npm run typecheck`
- [x] `npm run build`
- [x] authenticated Chrome save/rebind journey and before/after screenshots
- [x] local `GET /api/ready`: ready=true

final result: passed

---

# Design QA — 银行经营排名模板

- Result: passed
- Reference gallery: `/var/folders/5j/1tdj8bb17jbc5z_08kq65_bc0000gn/T/codex-clipboard-315fa27b-7c75-4f8e-809f-45526a96041f.png`
- Reference table: `/var/folders/5j/1tdj8bb17jbc5z_08kq65_bc0000gn/T/codex-clipboard-63d4ce31-58e2-49f9-8e2a-d6f1e80b3464.png`
- Implementation screenshots: `output/playwright/bank-performance-template/template-gallery.png`, `bank-performance-template-pivot.png`, `bank-performance-template-table.png`
- Same-input comparisons: `output/playwright/bank-performance-template/gallery-comparison.png`, `table-comparison.png`

## Visible comparison

- The gallery remains a viewport-level floating panel, uses the existing compact three-column preview system, and caps at 900 px or the viewport minus 80 px. Its content area owns vertical overflow; the chart card does not grow with the gallery.
- The custom section contains one compact, non-deletable `银行经营排名` tile. The tile previews the navy header, cool-blue grid and blue data-bar treatment.
- Both pivot and multi-dimensional table results preserve their current rows and labels while applying a navy header, navy total row, thin cool-blue borders, alternating pale-blue rows, an adjacent one-based ranking column and inset blue gradient data bars.
- The reference contains many score/rating/change fields that are absent from the browser fixture. The implementation intentionally applies only compatible current fields and does not invent screenshot rows, values, rating thresholds or change classifications.

## Interaction and state

- Real pointer click applies the featured template from the floating gallery.
- The pivot and multi-dimensional table retain data, rankings and column-maximum data bars when switching table type.
- Existing user-saved templates remain tenant/user scoped, deletable and limited to 20; the featured template does not consume that quota.
- Existing selected-row denominator progress rules remain compatible and fail closed when the row selector is incomplete.

---

# Design QA — 进度弹窗配色与正反渐变

- source visual truth: `/var/folders/5j/1tdj8bb17jbc5z_08kq65_bc0000gn/T/codex-clipboard-fc927e89-3e96-4cde-95fe-217a5a204c03.png`
- implementation screenshots: `output/playwright/progress-palette-20260830/progress-dialog.png`, `output/playwright/progress-palette-20260830/progress-palette-expanded.png`
- same-input comparisons: `output/playwright/progress-palette-20260830/progress-palette-collapsed-comparison.png`, `output/playwright/progress-palette-20260830/progress-palette-comparison.png`
- viewport: 1440×960 CSS px, device scale factor 1
- pixel normalization: source 2306×350 was scaled to 1044px wide and padded to 1044×260; the corresponding implementation color region was cropped at 1044×260; each combined comparison is 1044×520
- state: cross/multi-dimensional table metric header → 显示进度; comparison covers both the four-palette collapsed state and six-palette expanded dropdown state

## Findings

- No actionable P0/P1/P2 difference remains. The latest written requirements intentionally supersede the reference's five always-visible swatches and two gray group labels.
- Fonts and typography: module title, buttons and compact mode labels retain the existing SDA desktop typography; all three mode labels remain single-line and readable at 1440×960.
- Spacing and layout rhythm: dialog maximum width is 1044px and maximum height is 744px, each approximately 76px smaller than the previous maximum. Four primary swatches, the dropdown control and three fill-mode buttons remain on one row; the association-rule controls remain one rule per row.
- Colors and visual tokens: four restrained Office/Excel/Feishu/Primer-derived combinations are visible by default; the six additional combinations use the same two-tone preview grammar. Selected, hover and expanded states stay inside the existing green/neutral SDA token system.
- Image quality and asset fidelity: there are no raster product assets in this control; palette and progress previews are native UI color samples and remain sharp at device scale factor 1.
- Copy and content: the visible `经典配色` and `填充模式` labels are absent. Buttons read `正向渐变色`、`反向渐变色`、`完全色`; the extra palette trigger has an accessible label.

## Focused interaction evidence

- Initial DOM contains exactly four primary palette buttons and no expanded panel.
- Activating the compact arrow renders exactly six additional palette buttons in a floating 3×2 panel without increasing dialog height.
- Solid → reverse-gradient switching updates selected state and the live preview; saving preserves `reverse_gradient` through frontend normalization, backend projection and table-cell rendering.
- The expanded palette panel floats above the following section without shifting or wrapping the association-rule layout.
- The focused authenticated browser smoke completed with no console error and verified the saved reverse-gradient data bar in the table cell.

## Comparison history

- iteration 1: replaced five palettes with ten sourced combinations, removed the two redundant labels, added forward/reverse/solid modes and reduced the dialog frame.
- iteration 2: added explicit four-versus-six DOM assertions, an expanded-dropdown screenshot and a saved table-cell assertion for `reverse_gradient`; no P0/P1/P2 visual repair was required after the combined comparison.

## Verification

- [x] `npm run test:visualization-interaction`
- [x] `npm run typecheck`
- [x] `npm run build`
- [x] `python -m unittest backend.platform.tests.test_visual_reports` (15 tests)
- [x] authenticated focused browser journey for table enhancements and screenshots
- [x] collapsed and expanded same-input visual comparisons

final result: passed
