#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量提取日文原版 .msg 文件为 JSON 格式
所有 JSON 数据合并到一个文件中
"""

import json
import sys
from pathlib import Path

from extract_msg import parse_msg_file

# 默认路径配置
DEFAULT_FILES_JSON = Path("text/event/files.json")
DEFAULT_EXTRACTION_BASE = Path("extraction/PSP_GAME/USRDIR/pack/P2PT_ALL.cpk$/event.bin$")
DEFAULT_JSON_OUTPUT_FILE = Path("json/all.json")


def load_files_config(config_path: Path) -> dict:
    """加载 files.json 配置"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def batch_extract(config_path: Path, extraction_base: Path, output_file: Path):
    """
    批量提取所有 .msg 文件为 JSON，合并到一个文件
    
    Args:
        config_path: files.json 路径
        extraction_base: 日文原版文件的基础路径
        output_file: JSON 输出文件
    """
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # 所有 JSON 数据
    all_data = {}
    
    config = load_files_config(config_path)
    extracted_count = 0
    failed_files = []
    
    for file_key, file_path in config["files"].items():
        if not file_key.endswith(".msg"):
            continue
        
        # 构建完整的日文原版文件路径
        jp_file_path = extraction_base / file_path
        
        if not jp_file_path.exists():
            print(f"警告: 文件不存在，跳过: {jp_file_path}")
            failed_files.append(file_key)
            continue
        
        try:
            print(f"正在提取: {file_key}")
            json_data = parse_msg_file(jp_file_path)
            
            # 文件名（不含扩展名）作为 key
            file_key_base = file_key.replace(".msg", "")
            all_data[file_key_base] = json_data
            
            extracted_count += 1
        except Exception as e:
            print(f"错误: 提取 {file_key} 失败: {e}")
            failed_files.append(file_key)
    
    # 保存到单个文件
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n提取完成: 成功 {extracted_count} 个文件")
    print(f"输出文件: {output_file}")
    if failed_files:
        print(f"失败文件: {len(failed_files)} 个")
        for f in failed_files:
            print(f"  - {f}")


def main():
    # 如果提供了参数，使用参数；否则使用默认路径
    if len(sys.argv) >= 4:
        config_path = Path(sys.argv[1])
        extraction_base = Path(sys.argv[2])
        output_file = Path(sys.argv[3])
    else:
        config_path = DEFAULT_FILES_JSON
        extraction_base = DEFAULT_EXTRACTION_BASE
        output_file = DEFAULT_JSON_OUTPUT_FILE
        print(f"使用默认路径:")
        print(f"  files.json: {config_path}")
        print(f"  提取基础路径: {extraction_base}")
        print(f"  输出文件: {output_file}")
        print()
    
    batch_extract(config_path, extraction_base, output_file)


if __name__ == "__main__":
    main()

