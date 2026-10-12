// LibreSprite AI MCP: created 2026-10-11.
// Distributed under GNU GPL version 2 only (GPL-2.0-only); see the root LICENSE.
#pragma once

#include "../../../../nlohmann/json.hpp"
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace app { namespace automation {

// Complete rows, including transparent samples. Runs never cross a row boundary.
// Values are native unsigned packed RGBA/graya/index values, not rendered colors.
template<typename Read>
nlohmann::json pixelRows(int width, int height, const std::string& encoding, Read read) {
  if (width < 1 || height < 1 || width > 1024 || height > 1024 ||
      uint64_t(width) * height > 16384 || (encoding != "values" && encoding != "runs"))
    throw std::invalid_argument("Pixel reads require 1-16384 samples and values/runs encoding.");
  auto rows = nlohmann::json::array();
  for (int y = 0; y < height; ++y) {
    auto row = nlohmann::json::array();
    uint32_t previous = read(0, y); int length = 0;
    for (int x = 0; x < width; ++x) {
      uint32_t value = read(x, y);
      if (encoding == "values") row.push_back(value);
      else {
        if (length && value != previous) { row.push_back({length, previous}); length = 0; }
        previous = value; ++length;
      }
    }
    if (encoding == "runs") row.push_back({length, previous});
    rows.push_back(std::move(row));
  }
  return rows;
}

// Filter an explicit binary candidate mask to the 4/8-connected component at
// the seed. Nonmatching seeds return EMPTY, never a whole-region fallback.
inline std::string componentMask(int width, int height, const std::string& bits,
                                 int seedX, int seedY, int connectivity) {
  if (width < 1 || height < 1 || width > 1024 || height > 1024 ||
      uint64_t(width) * height > 262144 || bits.size() != std::size_t(width) * height ||
      bits.find_first_not_of("01") != std::string::npos || seedX < 0 || seedY < 0 ||
      seedX >= width || seedY >= height || (connectivity != 4 && connectivity != 8))
    throw std::invalid_argument("Component masks require bounded binary candidates and an in-region seed.");
  std::string selected(bits.size(), '0');
  int seed = seedY * width + seedX;
  if (bits[seed] != '1') return selected;
  std::vector<int> pending{seed}; selected[seed] = '1';
  while (!pending.empty()) {
    int index = pending.back(); pending.pop_back(); int x = index % width, y = index / width;
    for (int dy = -1; dy <= 1; ++dy) for (int dx = -1; dx <= 1; ++dx) {
      if ((!dx && !dy) || (connectivity == 4 && dx && dy)) continue;
      int xx = x + dx, yy = y + dy;
      if (xx < 0 || xx >= width || yy < 0 || yy >= height) continue;
      int next = yy * width + xx;
      if (bits[next] == '1' && selected[next] == '0') { selected[next] = '1'; pending.push_back(next); }
    }
  }
  return selected;
}

}} // namespace app::automation
