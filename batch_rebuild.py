#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量重组 JSON 文件为 .msg 文件，输出到对应位置
从 all.json 读取数据，重建为 .msg 文件
"""

import json
import shutil
import sys
from pathlib import Path

from extract_msg import rebuild_msg_file

# 默认路径配置
DEFAULT_JSON_FILE = Path("json/all.json")
DEFAULT_JSON_TRANSLATED_FILE = Path("json/all_translated.json")
DEFAULT_OUTPUT_BASE_DIR = Path("text/event")
DEFAULT_FILES_JSON = Path("text/event/files.json")
DEFAULT_EXTRACTION_BASE_DIR = Path("extraction/PSP_GAME/USRDIR/pack/P2PT_ALL.cpk$/event.bin$")


def load_files_config(config_path: Path) -> dict:
    """加载 files.json 配置"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def batch_rebuild(json_file: Path, output_base_dir: Path, config_path: Path = None, extraction_base_dir: Path = None):
    """
    批量重组所有 JSON 文件为 .msg 文件，输出到对应的位置
    同时从日文原版复制对应的 .script 文件
    
    Args:
        json_file: JSON 文件路径（包含所有文件的数据）
        output_base_dir: .msg 文件输出基础目录（如 text/event/）
        config_path: files.json 路径（用于确定输出文件名和源文件路径）
        extraction_base_dir: extraction 基础目录（用于查找原版 script 文件）
    """
    output_base_dir.mkdir(parents=True, exist_ok=True)
    
    # 如果提供了 config_path，加载配置以确定输出文件名和源文件路径
    file_map = {}
    script_path_map = {}
    if config_path and config_path.exists():
        config = load_files_config(config_path)
        for file_key, file_path in config["files"].items():
            if file_key.endswith(".msg"):
                # 从文件名提取基础名（如 E0000.msg -> E0000）
                base_name = file_key.replace(".msg", "")
                file_map[base_name] = file_key
            elif file_key.endswith(".script"):
                # 记录 script 文件的路径映射
                base_name = file_key.replace(".script", "")
                script_path_map[base_name] = file_path
    
    # 读取所有 JSON 数据
    print(f"正在读取: {json_file}")
    with open(json_file, 'r', encoding='utf-8') as f:
        all_data = json.load(f)
    
    rebuilt_count = 0
    copied_script_count = 0
    
    for file_key, json_data in all_data.items():
        try:
            # 确定输出文件名
            # 优先使用 files.json 中的文件名，否则使用 JSON key + .msg
            msg_filename = file_map.get(file_key, file_key + ".msg")
            msg_path = output_base_dir / msg_filename
            
            # 重建 .msg 文件
            msg_content = rebuild_msg_file(json_data)
            
            with open(msg_path, 'w', encoding='utf-8') as f:
                f.write(msg_content)
            
            print(f"已重组: {file_key} -> {msg_path}")
            rebuilt_count += 1
            
            # 复制对应的 .script 文件（如果存在）
            if extraction_base_dir:
                script_path = script_path_map.get(file_key)
                if script_path:
                    # 构建源文件路径
                    # script_path 格式如: "M003F.bin$/8.efb$/script.ef"
                    # extraction_base_dir 格式如: "extraction/PSP_GAME/USRDIR/pack/P2PT_ALL.cpk$/event.bin$"
                    # 完整路径: extraction_base_dir / script_path
                    source_script_path = extraction_base_dir / script_path
                    # 构建目标文件路径
                    script_filename = file_key + ".script"
                    target_script_path = output_base_dir / script_filename
                    
                    if source_script_path.exists():
                        # 复制文件
                        shutil.copy2(source_script_path, target_script_path)
                        print(f"  已复制: {source_script_path.name} -> {target_script_path}")
                        copied_script_count += 1
                    else:
                        # 调试信息：显示实际构建的路径
                        print(f"  警告: 源文件不存在: {source_script_path}")
                        # 检查 extraction_base_dir 是否存在
                        if not extraction_base_dir.exists():
                            print(f"    提示: extraction_base_dir 不存在: {extraction_base_dir}")
        except Exception as e:
            print(f"错误: 重组失败 {file_key}: {e}")
    
    print(f"\n重组完成: {rebuilt_count} 个 .msg 文件")
    if copied_script_count > 0:
        print(f"复制完成: {copied_script_count} 个 .script 文件")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="批量重组 JSON 文件为 .msg 文件，并复制日文原版的 .script 文件")
    parser.add_argument("--json", type=Path, default=None, help="JSON 文件路径（默认: json/all_translated.json，如果不存在则使用 json/all.json）")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_BASE_DIR, help="输出目录（默认: text/event）")
    parser.add_argument("--config", type=Path, default=DEFAULT_FILES_JSON, help="files.json 路径（默认: text/event/files.json）")
    parser.add_argument("--extraction", type=Path, default=DEFAULT_EXTRACTION_BASE_DIR, help="extraction 基础目录（默认: extraction/PSP_GAME/USRDIR/pack/P2PT_ALL.cpk$/event.bin$）")
    
    args = parser.parse_args()
    
    # 确定 JSON 文件路径
    if args.json is None:
        # 优先使用 all_translated.json，否则使用 all.json
        if DEFAULT_JSON_TRANSLATED_FILE.exists():
            json_file = DEFAULT_JSON_TRANSLATED_FILE
            print(f"使用翻译后的 JSON: {json_file}")
        else:
            json_file = DEFAULT_JSON_FILE
            print(f"使用原始 JSON: {json_file}")
    else:
        json_file = args.json
    
    # 调试：显示 extraction_base_dir
    extraction_dir = args.extraction
    print(f"extraction_base_dir: {extraction_dir}")
    print(f"extraction_base_dir 存在: {extraction_dir.exists()}")
    
    batch_rebuild(json_file, args.output, args.config, extraction_dir)


if __name__ == "__main__":
    main()

