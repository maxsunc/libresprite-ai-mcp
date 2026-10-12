// LibreSprite AI MCP: created 2026-10-11.
// Distributed under GNU GPL version 2 only (GPL-2.0-only); see the root LICENSE.
#pragma once

#include "../../../../nlohmann/json.hpp"
#include <cstdint>
#include <stdexcept>
#include <string>

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

}} // namespace app::automation
