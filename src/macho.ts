// GPL-2.0-only. Read load commands without requiring Xcode's otool on the user's Mac.
export function inspectMachO(bytes: Buffer): { dependencies: string[]; rpaths: string[]; minimumMacOS: string[] } {
  if (bytes.length < 32 || bytes.readUInt32LE(0) !== 0xfeedfacf || bytes.readUInt32LE(4) !== 0x0100000c) {
    throw new Error("Expected a thin arm64 Mach-O file.");
  }
  const count = bytes.readUInt32LE(16), commandsSize = bytes.readUInt32LE(20);
  if (count > 4096 || commandsSize > bytes.length - 32) throw new Error("Invalid Mach-O load command bounds.");
  const dependencies: string[] = [], rpaths: string[] = [], minimumMacOS: string[] = [];
  let position = 32;
  for (let i = 0; i < count; i++) {
    if (position + 8 > 32 + commandsSize) throw new Error("Truncated Mach-O load command.");
    const kind = bytes.readUInt32LE(position), size = bytes.readUInt32LE(position + 4);
    if (size < 8 || position + size > 32 + commandsSize) throw new Error("Invalid Mach-O load command size.");
    if ([0xc, 0x80000018, 0x8000001f, 0x80000023, 0x8000001c].includes(kind)) {
      const headerSize = kind === 0x8000001c ? 12 : 24;
      if (size < headerSize) throw new Error("Invalid Mach-O path command.");
      const offset = bytes.readUInt32LE(position + 8);
      if (offset < headerSize || offset >= size) throw new Error("Invalid Mach-O path offset.");
      const end = bytes.indexOf(0, position + offset);
      if (end < 0 || end >= position + size) throw new Error("Unterminated Mach-O path.");
      const value = bytes.toString("utf8", position + offset, end);
      (kind === 0x8000001c ? rpaths : dependencies).push(value);
    } else if (kind === 0x32 || kind === 0x24) {
      if (size < (kind === 0x32 ? 24 : 16)) throw new Error("Truncated Mach-O minimum-version command.");
      if (kind === 0x24 || bytes.readUInt32LE(position + 8) === 1) {
        const version = bytes.readUInt32LE(position + (kind === 0x32 ? 12 : 8));
        minimumMacOS.push(`${version >>> 16}.${(version >>> 8) & 255}.${version & 255}`);
      }
    }
    position += size;
  }
  if (position !== 32 + commandsSize) throw new Error("Mach-O load command count/size mismatch.");
  return { dependencies, rpaths, minimumMacOS };
}
