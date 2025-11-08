section("eboot");
org(0x8c7d56c);
sym("event2fontMap", () => {
  // 原始限制：0x0b45 (2885) - 支持到页码 11 的部分字符
  // 扩展限制：0x0c00 (3072) - 支持到页码 12 的完整字符
  // 这样可以支持更多字符，同时避免覆盖后续内存
  // 如果需要更多，可以逐步增加到 0x1000 (4096) 或 0x2000 (8192)
  // 但需要确保后续内存区域是安全的
  for (let i = 0; i < 0x0d00; i++) {
    let v = locale.font.utf2bin[locale.event.bin2utf[i]];
    if (locale.event.bin2utf[i] === undefined) v = 0;
    if (v === undefined){
      console.warn(`Unknown character mapping for ${i} ${locale.event.bin2utf[i]}`);
    }
    write_u16(locale.font.utf2bin[locale.event.bin2utf[i]]);
  }
});
