#!/usr/bin/env python3
"""
KiCad 元件标准化导入脚本 v1.0.3
==================================
从第三方来源（DigiKey/LCSC）将元件导入目标库，自动标准化语法格式。

用法：
    python kicad_import.py <源目录> <目标库根目录>

示例：
    python kicad_import.py D:/digikey/750311692 D:/MyLib

源目录应包含：*.kicad_sym, *.kicad_mod, *.step
目标库根目录应包含：库名.kicad_sym, 库名.pretty/, 库名.3dshapes/

注意：本脚本不会修改源目录中的任何文件。
"""
import re
import shutil
import sys
import os


# =====================================================================
# 工具函数
# =====================================================================

def extract_sexpr(text, start_idx):
    """从 text[start_idx] 开始提取一个完整的 S-Expression 块（括号平衡计数）。"""
    if start_idx >= len(text) or text[start_idx] != '(':
        return None, -1
    depth = 0
    i = start_idx
    in_str = False
    esc = False
    while i < len(text):
        c = text[i]
        if esc:
            esc = False
            i += 1
            continue
        if c == '\\':
            esc = True
            i += 1
            continue
        if c == '"':
            in_str = not in_str
            i += 1
            continue
        if not in_str:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return text[start_idx:i+1], i + 1
        i += 1
    return None, -1


def round4(val):
    return f"{float(val):.4f}"


def find_files(src_dir):
    """递归查找源目录中的 .kicad_sym, .kicad_mod, .step 文件。"""
    results = {'sym': None, 'mod': None, 'step': None}
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            lower = f.lower()
            if lower.endswith('.kicad_sym'):
                results['sym'] = os.path.join(root, f)
            elif lower.endswith('.kicad_mod'):
                results['mod'] = os.path.join(root, f)
            elif lower.endswith('.step') or lower.endswith('.stp'):
                results['step'] = os.path.join(root, f)
    return results


def get_lib_name(lib_root):
    """从目标库根目录提取库名（基于 .kicad_sym 文件名）。"""
    for f in os.listdir(lib_root):
        if f.endswith('.kicad_sym'):
            return f[:-10]
    raise ValueError(f"在 {lib_root} 中找不到 *.kicad_sym 文件")


# =====================================================================
# Step 3 — 封装标准化
# =====================================================================

def standardize_footprint(src_mod, dst_mod, lib_name, step_filename):
    """
    标准化封装文件格式。
    
    关键踩坑记录：
    - 只替换文件最后一个 ')'（封装根节点的关闭括号），不能跳过所有 ')' 行
      （fp_text 的关闭括号会被误跳过）
    - fp_text 的值可能是无引号的（REF**）或有引号的（"1"），需分别处理
    - fp_poly 展开为 fp_line 后，原 fp_poly 的关闭 ')' 需要跳过
    """
    with open(src_mod, 'r') as f:
        raw_lines = f.read().split('\n')
    
    result_lines = []
    i = 0
    last_nonempty_idx = max(
        (idx for idx, l in enumerate(raw_lines) if l.strip()),
        default=-1
    )
    
    while i < len(raw_lines):
        line = raw_lines[i]
        stripped = line.strip()
        
        if not stripped:
            i += 1
            continue
        
        # 最后一个非空行 = 封装的关闭括号
        if i == last_nonempty_idx:
            result_lines.append(
                f'  (model "${{{lib_name}}}/{lib_name}.3dshapes/{step_filename}"'
            )
            result_lines.append('    (offset (xyz 0.0000 0.0000 0.0000))')
            result_lines.append('    (scale (xyz 1.0000 1.0000 1.0000))')
            result_lines.append('    (rotate (xyz 0.0000 0.0000 0.0000))')
            result_lines.append('  )')
            result_lines.append(')')
            i += 1
            break
        
        # ——— Header ———
        hdr_m = re.match(r'\(footprint\s+(\S+)', stripped)
        if hdr_m:
            name = hdr_m.group(1)
            name_clean = name.strip('"')
            result_lines.append(
                f'(footprint "{name_clean}" (version 20221018) (generator nlbn)'
            )
            if '(layer ' not in stripped:
                result_lines.append('  (layer "F.Cu")')
            i += 1
            continue
        
        # ——— 跳过 tedit / descr / attr ———
        if (stripped.startswith('(tedit ') or
            stripped.startswith('(descr ') or
            stripped.startswith('(attr ')):
            i += 1
            continue
        
        # ——— fp_poly → fp_line ———
        if stripped.startswith('(fp_poly'):
            pts, poly_layer, poly_width = [], None, None
            i += 1
            while i < len(raw_lines):
                s = raw_lines[i].strip()
                for x_str, y_str in re.findall(r'xy\s+([-\d.]+)\s+([-\d.]+)', s):
                    pts.append((float(x_str), float(y_str)))
                em = re.search(r'\)\s*\(layer\s+(\S+)\)\s*\(width\s+([-\d.]+)\)', s)
                if em:
                    poly_layer = em.group(1)
                    poly_width = float(em.group(2))
                    i += 1
                    # 跳过 fp_poly 的关闭括号
                    if i < len(raw_lines) and raw_lines[i].strip() == ')':
                        i += 1
                    break
                if s == ')':
                    i += 1
                    break
                i += 1
            if pts and poly_layer and poly_width is not None:
                for j in range(len(pts)):
                    x1, y1 = pts[j]
                    x2, y2 = pts[(j + 1) % len(pts)]
                    result_lines.append(
                        f'  (fp_line (start {x1:.4f} {y1:.4f}) '
                        f'(end {x2:.4f} {y2:.4f})'
                    )
                    result_lines.append(
                        f'    (stroke (width {poly_width:.4f}) (type solid)) '
                        f'(layer "{poly_layer}")'
                    )
                    result_lines.append('  )')
            continue
        
        # ——— fp_text ———
        ft = re.match(
            r'\(fp_text\s+(\S+)\s+(?:"([^"]*)"|(\S+))\s+'
            r'\(at\s+([^)]+)\)\s+\(layer\s+(\S+)\)',
            stripped
        )
        if ft:
            ftype = ft.group(1)
            fval = ft.group(2) if ft.group(2) else ft.group(3)
            fat = ft.group(4)
            flayer = ft.group(5)
            result_lines.append(
                f'  (fp_text {ftype} "{fval}" (at {fat}) (layer "{flayer}")'
            )
            i += 1
            while i < len(raw_lines):
                s = raw_lines[i].strip()
                if s.startswith('(effects '):
                    result_lines.append(raw_lines[i])
                    i += 1
                elif s == ')':
                    result_lines.append('  )')
                    i += 1
                    break
                else:
                    i += 1
                    break
            continue
        
        # ——— Pad ———
        pm = re.match(
            r'\(pad\s+(\S+)\s+(smd\s+\w+|thru_hole\s+(?:circle|rect|oval))\s+'
            r'\(at\s+([^)]+)\)\s+\(size\s+([^)]+)\)\s+\(layers\s+([^)]+)\)',
            stripped
        )
        if pm:
            num = pm.group(1)
            ptype = pm.group(2)
            at_str = ' '.join(round4(v) for v in pm.group(3).split())
            sz_str = ' '.join(round4(v) for v in pm.group(4).split())
            layers = ' '.join(f'"{l}"' for l in pm.group(5).split())
            if not num.startswith('"'):
                num = f'"{num}"'
            result_lines.append(
                f'  (pad {num} {ptype} (at {at_str}) (size {sz_str}) '
                f'(layers {layers}))'
            )
            i += 1
            continue
        
        # ——— fp_line ———
        fl = re.match(
            r'\(fp_line\s+\(start\s+([^)]+)\)\s+\(end\s+([^)]+)\)\s+'
            r'\(layer\s+(\S+)\)\s+\(width\s+([^)]+)\)\s*\)',
            stripped
        )
        if fl:
            start = fl.group(1)
            end = fl.group(2)
            layer = fl.group(3)
            w = float(fl.group(4))
            result_lines.append(f'  (fp_line (start {start}) (end {end})')
            result_lines.append(
                f'    (stroke (width {w:.4f}) (type solid)) (layer "{layer}")'
            )
            result_lines.append('  )')
            i += 1
            continue
        
        # ——— fp_circle ———
        fc = re.match(
            r'\(fp_circle\s+\(center\s+([^)]+)\)\s+\(end\s+([^)]+)\)\s+'
            r'\(layer\s+(\S+)\)\s+\(width\s+([^)]+)\)\s*\)',
            stripped
        )
        if fc:
            center = ' '.join(round4(v) for v in fc.group(1).split())
            end = ' '.join(round4(v) for v in fc.group(2).split())
            layer = fc.group(3)
            w = float(fc.group(4))
            result_lines.append(f'  (fp_circle (center {center}) (end {end})')
            result_lines.append(
                f'    (stroke (width {w:.4f}) (type solid)) (fill none) '
                f'(layer "{layer}")'
            )
            result_lines.append('  )')
            i += 1
            continue
        
        # ——— 其他行直接保留 ———
        result_lines.append(line)
        i += 1
    
    output = '\n'.join(result_lines) + '\n'
    
    opens = output.count('(')
    closes = output.count(')')
    if opens != closes:
        print(f"  ⚠️ 封装括号不平衡！({opens} open, {closes} close)")
    
    with open(dst_mod, 'w') as f:
        f.write(output)
    return output


# =====================================================================
# Step 5 — 符号合并
# =====================================================================

def merge_symbol(src_sym, dst_sym_file, lib_name, mod_name):
    """
    从源符号文件中提取符号块，修改 Footprint 属性后合并入目标文件。
    使用 S-Expression 解析器确保完整提取。
    """
    with open(src_sym, 'r') as f:
        src = f.read()
    
    # 查找所有 (symbol "NAME" ...) 块
    symbols = []
    idx = 0
    while True:
        m = re.search(r'\(symbol\s+"([^"]*)"', src[idx:])
        if not m:
            break
        abs_start = idx + m.start()
        block, end_pos = extract_sexpr(src, abs_start)
        if block:
            symbols.append((m.group(1), block))
            idx = end_pos
        else:
            idx = abs_start + 1
    
    if not symbols:
        print("  ❌ 源文件中未找到任何 (symbol ...) 块")
        return False
    
    print(f"  📄 找到 {len(symbols)} 个符号: {[s[0] for s in symbols]}")
    
    with open(dst_sym_file, 'r') as f:
        target = f.read()
    
    for sym_name, sym_block in symbols:
        # 修改 Footprint 属性
        sym_block = re.sub(
            r'\(property\s+"Footprint"\s+"[^"]*"\s*\(id\s+2\)',
            f'(property "Footprint" "{lib_name}:{mod_name}" (id 2)',
            sym_block
        )
        
        # 删除目标中已存在的同名符号
        if f'(symbol "{sym_name}"' in target:
            old_idx = target.find(f'(symbol "{sym_name}"')
            old_block, end_idx = extract_sexpr(target, old_idx)
            if old_block:
                print(f"  ⚠️ 符号 '{sym_name}' 已存在，替换中...")
                target = target[:old_idx] + target[end_idx:]
        
        # 在 kicad_symbol_lib 关闭前插入
        target = target.rstrip()
        last_close = target.rfind('\n)')
        if last_close >= 0:
            target = target[:last_close] + '\n\n' + sym_block + '\n)'
        else:
            target = target[:-1] + '\n' + sym_block + '\n)'
    
    # 校验括号平衡
    opens = target.count('(')
    closes = target.count(')')
    if opens != closes:
        print(f"  ⚠️ 符号文件括号不平衡！({opens} open, {closes} close)")
        return False
    
    with open(dst_sym_file, 'w') as f:
        f.write(target)
    print(f"  ✅ 平衡校验通过 ({opens} open, {closes} close)")
    return True


# =====================================================================
# 主流程
# =====================================================================

def main():
    if len(sys.argv) < 3:
        print("用法: python kicad_import.py <源目录> <目标库根目录>")
        sys.exit(1)
    
    src_dir = os.path.abspath(sys.argv[1])
    lib_root = os.path.abspath(sys.argv[2])
    
    print("=" * 60)
    print(f"KiCad 元件标准化导入")
    print(f"源目录:     {src_dir}")
    print(f"目标库:     {lib_root}")
    print("=" * 60)
    
    # Step 1: 校验目标库结构
    if not os.path.isdir(lib_root):
        print(f"❌ 目标库目录不存在: {lib_root}")
        sys.exit(1)
    
    try:
        lib_name = get_lib_name(lib_root)
        print(f"   库名: {lib_name}")
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    # Step 2: 查找源文件
    files = find_files(src_dir)
    print(f"\n--- Step 2: 查找源文件 ---")
    for k, v in files.items():
        print(f"   {k}: {v if v else '❌ 未找到'}")
    
    if not files['mod']:
        print("❌ 未找到 .kicad_mod 文件")
        sys.exit(1)
    
    mod_basename = os.path.basename(files['mod'])
    mod_name = mod_basename[:-10]
    
    step_filename = None
    if files['step']:
        step_filename = os.path.basename(files['step'])
    
    # Step 3: 转换封装
    print(f"\n--- Step 3: 转换封装 ---")
    dst_mod_dir = os.path.join(lib_root, f"{lib_name}.pretty")
    os.makedirs(dst_mod_dir, exist_ok=True)
    dst_mod = os.path.join(dst_mod_dir, mod_basename)
    standardize_footprint(files['mod'], dst_mod, lib_name, step_filename)
    print(f"   ✅ {dst_mod}")
    
    # Step 4: 复制 3D 模型
    if files['step']:
        print(f"\n--- Step 4: 复制 3D 模型 ---")
        dst_3d_dir = os.path.join(lib_root, f"{lib_name}.3dshapes")
        os.makedirs(dst_3d_dir, exist_ok=True)
        dst_step = os.path.join(dst_3d_dir, step_filename)
        shutil.copy2(files['step'], dst_step)
        print(f"   ✅ {dst_step}")
    
    # Step 5: 合并符号
    if files['sym']:
        print(f"\n--- Step 5: 合并符号 ---")
        dst_sym_file = os.path.join(lib_root, f"{lib_name}.kicad_sym")
        merge_symbol(files['sym'], dst_sym_file, lib_name, mod_name)
        print(f"   ✅ 符号合并完成")
    
    # Step 6: 更新 checkpoint
    checkpoint_file = os.path.join(lib_root, '.checkpoint')
    with open(checkpoint_file, 'w') as f:
        with open(os.path.join(lib_root, f"{lib_name}.kicad_sym")) as sf:
            content = sf.read()
        names = re.findall(r'\(symbol\s+"([^"]+)"', content)
        for name in names:
            f.write(f'{name}\n')
    print(f"\n--- Step 6: 更新 checkpoint ---")
    print(f"   ✅ {os.path.basename(checkpoint_file)}")
    
    print(f"\n{'=' * 60}")
    print(f"✅ 导入完成！")
    print(f"{'=' * 60}")
    
    # Step 7: 提示待办
    print(f"\n--- Step 7: 请用户提供以下信息 ---")
    print(f"1. 货源 URL (用于补填 Datasheet/Description)")
    print(f"2. 3D 模型调整参数 (当前默认: offset=0, scale=1, rotate=0)")


if __name__ == '__main__':
    main()
