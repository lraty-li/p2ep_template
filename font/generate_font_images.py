#!/usr/bin/env python3
"""
生成字体图片脚本
从字体文件生成字体图片，同时生成 font_info.json
每个图片是 16x16 字符网格，每个字符 16x16 像素，总共 256x256 像素
"""

import json
import os
from PIL import Image, ImageDraw, ImageFont
import sys

# 字符网格大小
CHAR_SIZE = 16  # 每个字符 16x16 像素
GRID_SIZE = 16  # 16x16 网格
IMAGE_SIZE = CHAR_SIZE * GRID_SIZE  # 256x256 像素

def analyze_char(char_img):
    """分析单个字符图片，返回 left 和 width（与生成图片时同步）"""
    # 找到最左边和最右边的非透明像素
    minx = CHAR_SIZE
    maxx = 0
    
    pixels = char_img.load()
    for y in range(CHAR_SIZE):
        for x in range(CHAR_SIZE):
            # 检查 alpha 通道（透明度）
            if len(pixels[x, y]) == 4:  # RGBA
                r, g, b, a = pixels[x, y]
                if a > 0:  # 非透明像素
                    if minx > x:
                        minx = x
                    if maxx < x:
                        maxx = x
            else:  # RGB 或其他格式
                # 假设白色像素是字符
                if pixels[x, y] != (0, 0, 0) and pixels[x, y] != 0:
                    if minx > x:
                        minx = x
                    if maxx < x:
                        maxx = x
    
    # 如果没有找到任何像素（空字符），返回默认值
    if minx == CHAR_SIZE:
        return 0, 4  # 默认空格宽度
    
    left = minx
    # width = 实际宽度 + 1像素边距，最大不超过14（因为left+width不能超过15）
    width = min(maxx - left + 2, 14)
    
    return left, width

def load_font(font_path, size=12):
    """加载字体文件（像素字体通常使用12px）"""
    try:
        # 像素字体通常设计为12px，我们加载这个大小
        font = ImageFont.truetype(font_path, size)
        # 保存字体路径以便后续使用
        font.path = font_path
        return font
    except Exception as e:
        print(f"警告: 无法加载字体 {font_path}: {e}")
        # 使用默认字体
        try:
            font = ImageFont.load_default()
            font.path = None
            return font
        except:
            return None

def render_char(char, font, char_size=16, font_size=12):
    """渲染单个字符到图片（像素字体，左对齐，与游戏渲染逻辑一致）"""
    if not char or char == "":
        # 空字符，返回透明图片
        return Image.new('RGBA', (char_size, char_size), (0, 0, 0, 0))
    
    # 创建临时图片用于测量字符边界框
    temp_img = Image.new('RGBA', (char_size * 2, char_size * 2), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp_img)
    
    # 获取字符边界框（包括 left bearing）
    try:
        bbox = temp_draw.textbbox((0, 0), char, font=font)
        # bbox 返回 (left, top, right, bottom)
        # left 可能是负数（字符超出左边界）
        text_left = bbox[0]
        text_top = bbox[1]  # top 可能是负数（字符超出上边界）
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    except:
        text_left = 0
        text_top = 0
        text_width = char_size
        text_height = char_size
    
    # Y方向：顶部对齐（与游戏渲染逻辑一致）
    # 如果 top bearing 为负（字符超出上边界），需要调整渲染位置
    y_offset = max(0, -text_top)
    
    # X方向：左对齐，从0开始
    # 如果 left bearing 为负，需要调整渲染位置以避免字符被裁剪
    x_offset = 0
    render_x = x_offset - min(0, text_left)
    
    # 创建字符图片
    char_img = Image.new('RGBA', (char_size, char_size), (0, 0, 0, 0))
    char_draw = ImageDraw.Draw(char_img)
    
    # 渲染字符（左对齐，顶部对齐）
    try:
        char_draw.text((render_x, y_offset), char, font=font, fill=(255, 255, 255, 255))
    except Exception as e:
        print(f"警告: 无法渲染字符 '{char}': {e}")
        return Image.new('RGBA', (char_size, char_size), (0, 0, 0, 0))
    
    return char_img

def generate_font_page(page_num, page_data, font, output_path, font_info_list=None):
    """生成单个字体页面图片，同时收集字体信息"""
    # 创建 256x256 的图片
    img = Image.new('RGBA', (IMAGE_SIZE, IMAGE_SIZE), (0, 0, 0, 0))
    
    # 遍历 16x16 网格
    for y in range(GRID_SIZE):
        if y >= len(page_data):
            break
        row = page_data[y]
        for x in range(GRID_SIZE):
            if x >= len(row):
                break
            
            char = row[x]
            
            # 计算字符编码
            char_code = page_num * 256 + y * 16 + x
            
            # 渲染字符（使用12px字体，渲染到16x16格子）
            char_img = render_char(char, font, CHAR_SIZE, font_size=12)
            
            # 计算在图片中的位置
            x_pos = x * CHAR_SIZE
            y_pos = y * CHAR_SIZE
            
            # 将字符图片粘贴到主图片上（只有非空字符才粘贴）
            if char != "":
                img.paste(char_img, (x_pos, y_pos), char_img)
            
            # 分析字符并添加到 font_info（只处理非空字符）
            if font_info_list is not None and char != "":
                left, width = analyze_char(char_img)
                
                font_info_list.append({
                    "char": char,
                    "left": left,
                    "width": width
                })
    
    # 保存图片
    img.save(output_path, 'PNG')
    print(f"已生成: {output_path} (页码 {page_num})")

def main():
    # 路径配置
    script_dir = os.path.dirname(os.path.abspath(__file__))
    font_path = os.path.join(script_dir, 'fusion-pixel-12px-monospaced-zh_hans.otf.woff')
    font_json_path = os.path.join(script_dir, 'locale', 'font.json')
    output_dir = script_dir
    
    # 检查字体文件
    if not os.path.exists(font_path):
        print(f"错误: 找不到字体文件: {font_path}")
        sys.exit(1)
    
    # 检查 font.json
    if not os.path.exists(font_json_path):
        print(f"错误: 找不到 font.json: {font_json_path}")
        sys.exit(1)
    
    # 加载 font.json
    print(f"加载字体映射: {font_json_path}")
    with open(font_json_path, 'r', encoding='utf-8') as f:
        font_data = json.load(f)
    
    # 加载字体（像素字体通常使用12px）
    print(f"加载字体文件: {font_path}")
    font = load_font(font_path, size=12)
    if font is None:
        print("错误: 无法加载字体")
        sys.exit(1)
    
    # 生成所有页码的字体图片（0-31），同时生成 font_info.json
    start_page = 0
    end_page = 31
    
    # 用于收集字体信息（处理所有字符）
    font_info_list = []
    
    print(f"\n开始生成字体图片 (页码 {start_page} 到 {end_page})...")
    
    for page_num in range(start_page, end_page + 1):
        page_key = str(page_num)
        if page_key not in font_data:
            print(f"跳过页码 {page_num}: 在 font.json 中不存在")
            continue
        
        page_data = font_data[page_key]
        output_path = os.path.join(output_dir, f'font{page_num}.png')
        
        # 生成图片并收集字体信息
        generate_font_page(page_num, page_data, font, output_path, font_info_list)
    
    print(f"\n完成! 已生成页码 {start_page} 到 {end_page} 的字体图片")
    
    # 保存 font_info.json
    if font_info_list:
        font_info_path = os.path.join(output_dir, 'font_info.json')
        print(f"\n保存字体信息到: {font_info_path}")
        with open(font_info_path, 'w', encoding='utf-8') as f:
            json.dump(font_info_list, f, ensure_ascii=False, indent=4)
        print(f"完成! 已生成 {len(font_info_list)} 个字符的字体信息")
    
    # 更新 files.json
    update_files_json(script_dir, start_page, end_page)

def update_files_json(script_dir, start_page, end_page):
    """更新 files.json，确保所有生成的 font*.png 都在其中"""
    files_json_path = os.path.join(script_dir, 'files.json')
    
    if not os.path.exists(files_json_path):
        print(f"\n警告: 未找到 files.json: {files_json_path}")
        return
    
    # 读取现有的 files.json
    print(f"\n读取 files.json: {files_json_path}")
    with open(files_json_path, 'r', encoding='utf-8') as f:
        files_data = json.load(f)
    
    # 检查实际生成的 font*.png 文件
    generated_fonts = []
    for page_num in range(start_page, end_page + 1):
        font_filename = f'font{page_num}.png'
        font_path = os.path.join(script_dir, font_filename)
        if os.path.exists(font_path):
            generated_fonts.append(font_filename)
    
    # 更新 files.json 的 files 部分
    if 'files' not in files_data:
        files_data['files'] = {}
    
    # 计算对应的 gim 路径（从 font0.png 对应 5.gim$ 开始）
    base_gim_index = 5
    
    updated_count = 0
    for font_filename in generated_fonts:
        # 从 font0.png 提取页码
        try:
            page_num = int(font_filename.replace('font', '').replace('.png', ''))
            gim_index = base_gim_index + page_num
            gim_path = f"{gim_index}.gim$/image.png"
            
            # 更新或添加条目
            if font_filename not in files_data['files']:
                files_data['files'][font_filename] = []
            
            # 检查是否已有对应的 gim 路径
            found = False
            for entry in files_data['files'][font_filename]:
                if entry.get('path') == gim_path:
                    found = True
                    break
            
            if not found:
                # 如果没有找到，更新为正确的路径（替换所有旧条目）
                files_data['files'][font_filename] = [{
                    "path": gim_path,
                    "args": { "useSourcePalette": True, "matchPalette": True }
                }]
                updated_count += 1
        except ValueError:
            # 如果不是标准格式的 font*.png，跳过
            continue
    
    # 保存更新后的 files.json
    if updated_count > 0 or len(generated_fonts) > 0:
        print(f"\n更新 files.json...")
        with open(files_json_path, 'w', encoding='utf-8') as f:
            json.dump(files_data, f, ensure_ascii=False, indent=2)
        print(f"完成! 已更新 {len(generated_fonts)} 个字体图片条目到 files.json")

if __name__ == '__main__':
    main()

