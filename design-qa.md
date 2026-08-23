# 登录页调查模块紧凑布局 Design QA

**Findings**

- 当前无未解决的 P0/P1/P2 问题。
- 已修复 [P2] 调查模块下方存在额外说明块和过长留白：删除说明块，将双栏卡片收敛到 `900px`，问题间距改为紧凑节奏，两个文本框保持完整可见并允许用户纵向扩展。

**Comparison target**

- Source visual truth: `/var/folders/5j/1tdj8bb17jbc5z_08kq65_bc0000gn/T/codex-clipboard-14561b74-d90d-4688-a8b0-cd92e1796a28.png`
- Browser-rendered implementation: `http://127.0.0.1:5174/login`
- Desktop implementation screenshot: `/Users/revan/.codex/visualizations/2026/08/22/01a02742-893f-7570-80e4-3bc27203c487/login-survey-implementation-desktop.png`
- Mobile implementation screenshot: `/Users/revan/.codex/visualizations/2026/08/22/01a02742-893f-7570-80e4-3bc27203c487/login-survey-implementation-mobile.png`
- Full-view comparison: `/Users/revan/.codex/visualizations/2026/08/22/01a02742-893f-7570-80e4-3bc27203c487/login-survey-source-vs-implementation.png`
- Focused card comparison: `/Users/revan/.codex/visualizations/2026/08/22/01a02742-893f-7570-80e4-3bc27203c487/login-survey-focused-comparison.png`

**Viewport and normalization**

- Source pixels: `2026 × 1294`; source top red-box region is the requested visual/content target and the lower red-box explanation is explicitly excluded.
- Desktop CSS viewport: `1440 × 900`; rendered card measured `900 × 455.5` CSS px, centered at `x=270`, `y=222.25`; page has `scrollWidth=1440` and no horizontal overflow.
- In-app Browser screenshot surface is half-scale relative to measured CSS coordinates; the focused implementation crop uses the corresponding `450 × 228` raster region and only scales for visual comparison.
- Mobile CSS viewport: `390 × 844`; full-page content height `946`, main card width `358`, `scrollWidth=390`, no horizontal overflow.
- State: login mode; survey fields blank; institution `华兴银行`. Browser autofill supplied local QA-only account/password values in screenshots; they were not submitted.

**Full-view comparison evidence**

- The unified split card keeps the source's pale-green survey pane, white login pane, restrained border/radius/shadow and green primary color.
- The deleted lower explanation is absent from visible text and DOM. Survey pane height now follows the compact login card instead of extending the whole shell.
- Desktop columns are equal width, so the survey module follows the login module's scale. Mobile retains a single stacked card and natural vertical scrolling.

**Focused region comparison evidence**

- Both questions, labels, placeholders and counters are fully visible. Desktop textareas measure `392 × 92`; mobile measures `308 × 92`; `scrollHeight=90`, so the empty state is not clipped.
- Survey labels, input borders, radii, type scale and focus tokens remain aligned with the existing login form.
- No focused image/asset comparison is required: the screen contains only existing Lucide icons and form controls, with no raster illustration, logo artwork or generated image.

**Required fidelity surfaces**

- Fonts and typography: existing system font stack and hierarchy retained; no title, placeholder, label or counter truncation observed.
- Spacing and layout rhythm: outer width reduced from `980px` to `900px`; pane padding is `24–28px`; question gap is `14px`; login-form gap is `14px`; no excess lower whitespace remains inside the card.
- Colors and visual tokens: existing `#0f8554` primary green, pale-green survey surface, white form surface, neutral borders and soft elevation retained.
- Image quality and asset fidelity: existing Lucide icons are reused; no placeholder, emoji, CSS drawing or handcrafted SVG was introduced.
- Copy and content: the two required questions and original login copy remain. The bottom auto-save explanation is removed exactly as requested; saving behavior remains invisible and unchanged.

**Primary interactions and runtime checks**

- Survey fields are blank on load and the survey subtree contains `0` buttons。
- The removed explanation text is absent.
- Login, registration and cancel controls remain present; credential gating is unchanged.
- Desktop and mobile have no horizontal overflow; mobile supports vertical scrolling to the complete login section.
- Browser console after desktop and mobile reload: `0` warnings/errors.
- Login/cancel/page-close persistence remains covered by the focused auth/message-board tests; no persistence handler was changed in this visual adjustment.

**Comparison history**

1. Earlier implementation added the survey and automatic persistence but left a bottom explanation block, causing the survey column to make the shared card taller than the login content.
2. The explanation block was removed, both columns were normalized to equal width, textarea height and inter-field spacing were reduced, and resize-y was retained for longer answers.
3. Post-fix desktop evidence shows a `900 × 455.5` card with both textareas complete and no lower internal blank region. Post-fix `390 × 844` evidence shows no horizontal overflow or clipping. No actionable P0/P1/P2 findings remain.

**Implementation Checklist**

- [x] Remove the lower survey explanation.
- [x] Keep both survey questions, placeholders and counters complete.
- [x] Match survey and login module scale.
- [x] Reduce excessive label/input and question spacing.
- [x] Preserve login, cancel and page-close survey persistence.
- [x] Verify desktop, mobile, visible DOM and console.

**Follow-up Polish**

- No P3 polish is required for handoff.

final result: passed
