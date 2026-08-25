# 定时任务 Tab 系统风格收敛 QA

- source visual truth: `/var/folders/5j/1tdj8bb17jbc5z_08kq65_bc0000gn/T/codex-clipboard-9cb9e7d1-7757-4519-abbb-87df1a813f90.png`
- implementation screenshot: `/Users/revan/Documents/Smart_Data_Agent/schedule-tab-system-refined.png`
- calendar screenshot: `/Users/revan/Documents/Smart_Data_Agent/schedule-tab-calendar-refined.png`
- combined comparison: `/Users/revan/Documents/Smart_Data_Agent/schedule-tab-reference-comparison.png`
- browser: Codex in-app Browser，SDA 本地服务 `127.0.0.1:5174`
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
