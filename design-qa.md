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
