---
name: component-standardized-importer
description: Import DigiKey/LCSC/etc. KiCad components (symbol + footprint + 3D model) into a standardized local library. Trigger when user provides a source folder containing .kicad_mod, .kicad_sym, and .step files, plus a target library root path.
version: 1.0.2
agent_created: true
---

# KiCad 元件导入工具

## Overview

将第三方来源（DigiKey、LCSC 等）的 KiCad 元件，按用户库的语法规范标准化后，自动整理并合并到目标库中。

**典型触发场景：** 用户提供源文件夹路径和目标库路径，要求导入元件。

**重要处理原则：** 执行过程中不需要中途停下来问用户问题。所有需要用户填写的内容（货源 URL、3D 模型调整表），**全部在最后一次性提出**。

## 工作流

### Step 1 — 用户输入

用户提供两项：
- **源文件夹路径**（如 `D:\...\digikey\750311692\`）——内含元件的符号、封装、3D 模型
- **目标库根路径**（如 `D:\...\TEST\lib\`）——结构须为：
  - `库名.3dshapes/` ← 3D 模型存放
  - `库名.pretty/` ← 封装存放
  - `库名.kicad_sym` ← 符号合并到此文件

### Step 2 — 递归遍历源文件夹

源文件夹可能有多层子目录嵌套，递归查找以下文件：
- `*.kicad_mod` → 封装文件
- `*.kicad_sym` → 符号文件（如果存在一个 `kicad_symbol_lib` 包裹的完整库文件，从中提取每个 `(symbol "NAME"...` 块）
- `*.step` → 3D 模型文件
- 同时支持 `.kicad.txt` 扩展名（等同于 `.kicad_mod`）

### Step 3 — 转换封装文件（不需用户输入，直接执行）

从目标库路径中提取**库名**：目标库根目录下的 `xxx.kicad_sym` 文件名即为库名（如 `library.kicad_sym` → 库名为 `library`）。

只做**语法格式转换**，不修改任何物理尺寸、引脚位置、图形坐标等数据。

**需转换的项目：**
- Header：`(footprint "名称" (version YYYYMMDD) (generator nlbn))` → 去掉 tedit/descr/attr
- 字符串加引号：封装名、层名、焊盘编号
- Pad 格式：去掉 `solder_mask_margin`
- fp_line：`(layer ...) (width ...)` → `(stroke (width w) (type solid)) (layer "...")`
- fp_circle：同上 + `(fill none)`
- fp_poly → 拆成多条 fp_line
- 数值精度统一为 4 位小数

**禁止修改：**
- 焊盘位置、尺寸、钻孔直径
- 焊盘编号
- 所有图形元素的位置和尺寸
- 所有 `fp_text` 的坐标
- 3D 模型的 offset/scale/rotate（保持原样）

**需添加（参考目标库中已有封装的写法）：**
- 在文件末尾、`)` 结束之前，添加 3D 模型引用，路径格式为 `${库名}/库名.3dshapes/模型文件名.step`
- 如果源封装已有 `(model ...)` 块，保留其 offset/scale/rotate 值不变

### Step 4 — 复制 3D 模型（不需用户输入，直接执行）

将 `.step` 文件复制到 `库名.3dshapes/` 目录。

### Step 5 — 处理符号文件（不需用户输入，直接执行）

从源 `.kicad_sym` 文件中提取 `(symbol "NAME" ...)` 块：
1. 读取目标 `库名.kicad_sym`，检查是否已有同名符号
2. **有则替换**，**无则追加**
3. 修改符号内的 `(property "Footprint" ...)` 为 `"库名:封装名"`
4. Datasheet、Description、DK Part 等附加属性**暂不填写**，留到最终问用户后补填

**符号格式转换：**
- 字符串加引号
- 读取目标 `库名.kicad_sym` 中已存在的符号，分析其 property 格式、indent 风格、stroke 写法，使新插入的符号与之完全一致
- 具体需对齐的点（**以下只是举例，最终以目标库中已有符号的真实写法为准**）：
  - **Color**：观察目标库中 arc/stroke 是否包含 `(color ...)` 字段——有则保留，无则去除
  - **hide 写法**：目标库可能用 `(hide yes)`、裸 `hide` 标志、或 `) hide)` 三种之一——仔细参考已有符号
  - **property 格式**：目标库可能使用多行 id 格式 `(property "Name" "Value" (id N) ...)` 或单行紧凑格式——对齐
  - **缩进和括号间距**：观察已有符号的缩进层级、`(effects (font (size s s) )` 里的空格习惯，保持一致
- 只改语法，不改引脚编号、位置、长度、图形

### Step 6 — 符号合并后结构校验（关键！）

合并完成后，必须验证目标 `库名.kicad_sym` 的 **S-Expression 括号结构** 完整：
1. 确保 `(symbol ...)` 块全部位于 `(kicad_symbol_lib ...)` 内部
2. 读开头和结尾各几行，检查没有**多余括号**导致符号被甩到库外面
3. 具体来说：检查每个 `(symbol ...)` 的缩进是否与同级符号一致

**典型错误：** 追加符号后多了一个 `)` 提前关闭了 `kicad_symbol_lib`，导致新符号成为游离的孤儿符号（KiCad 完全读不到它）。

### Step 7 — 一次性向用户提问，收集信息后补填

完成上述所有处理（文件已写入库）后，**一次性**向用户提出以下所有问题：

**问题 A — 货源网址：** 询问商品页面 URL（如 DigiKey、LCSC、Mouser 等）。用户回复后：
1. 用 WebFetch 或 WebSearch 获取数据手册 URL、型号描述
2. 从 URL 或页面内容中提取货源编号
3. 如果货源是 DigiKey，编号前加 `DJ` 前缀
4. 将以上信息填入符号的 Datasheet、Description、DK Part 属性

**问题 B — 3D 调整表：** 提交结构化的 3D 模型调整表格，包含当前 9 个参数：

| 轴 | Scale | Offset | Rotate |
|----|-------|--------|--------|
| X | 当前值 | 当前值 | 当前值 |
| Y | 当前值 | 当前值 | 当前值 |
| Z | 当前值 | 当前值 | 当前值 |

表格中填写当前封装文件中该模型的原始值。用户如果修改后发回，按新值更新；如果没修改直接反馈（或不回复），保持不动。

**注意：** 如果源封装没有 `(model ...)` 块，offset/scale/rotate 全部填 0，用户可自行调整。

### 规范化规则摘要

| 规则 | 说明 |
|------|------|
| 精度 | 所有数值统一 4 位小数 |
| 引号 | 名称、层名、焊盘编号全部加双引号 |
| fp_line | `(stroke (width w) (type solid)) (layer "层名")` |
| fp_circle | `(stroke (width ...) (type solid)) (fill none) (layer "...")` |
| 焊盘 | THT: `(layers "*.Cu" "*.Mask") (drill d)` ; SMD: `(layers "F.Cu" "F.Mask" "F.Paste")` |
| 3D 路径 | `${库名}/库名.3dshapes/文件名.step`（从目标库中已有封装获取模板） |
| 旋转 | 绝对值不超过 180°（用户约定） |
| 编号前缀 | DigiKey 货源加 `DJ`，LCSC 货源加 `C`（保持原样） |

---

## 版本迭代规则

本 skill 以 `component-standardized-importer_vX.Y.Z` 目录组织版本：

1. **不修改历史版本**：每次迭代在母目录下**新建版本目录**，不在原有目录上直接修改。
2. **只改最后一个版本**：优化、修复只针对最新版本目录，历史版本保持冻结。
3. **版本号规则**：语义化版本。修复性更新 → Z+1，功能性更新 → Y+1，重大重构 → X+1。
4. **文件完整性**：每个版本目录自包含所有必需文件（SKILL.md + scripts/ + assets/ + references/），不依赖外部文件。
