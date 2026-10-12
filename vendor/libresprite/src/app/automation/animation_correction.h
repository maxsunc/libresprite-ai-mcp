// LibreSprite AI MCP: created 2026-10-09.
// Distributed under GNU GPL version 2 only (GPL-2.0-only); see the root LICENSE.
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace app { namespace automation {

inline bool validCorrectionMask(int width, int height, const std::string& bits) {
  return width >= 1 && width <= 1024 && height >= 1 && height <= 1024 &&
         bits.size() <= 262144 && bits.size() == std::size_t(width) * height &&
         bits.find_first_not_of("01") == std::string::npos && bits.find('1') != std::string::npos;
}

// Caller validates the mask/source/destination bounds and supplies a read function
// over the ORIGINAL cel, never the patch being written. Sparse holes are untouched;
// selected transparent samples replace destinations, too. Raw RGBA/index/gray values
// are copied without blending, resampling or palette conversion.
template<typename Read, typename Write>
void translateCorrectionRegion(int x, int y, int width, int height,
                               const std::string& bits, int dx, int dy, bool copy,
                               uint32_t clear, Read read, Write write) {
  if (!copy)
    for (int yy = 0; yy < height; ++yy) for (int xx = 0; xx < width; ++xx)
      if (bits[yy * width + xx] == '1') write(x + xx, y + yy, clear);
  for (int yy = 0; yy < height; ++yy) for (int xx = 0; xx < width; ++xx)
    if (bits[yy * width + xx] == '1') write(x + xx + dx, y + yy + dy, read(x + xx, y + yy));
}

}} // namespace app::automation
