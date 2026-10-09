// LibreSprite AI MCP: created 2026-10-09.
// Distributed under GNU GPL version 2 only (GPL-2.0-only); see the root LICENSE.
#pragma once

#include "doc/color.h"
#include "../../../../nlohmann/json.hpp"
#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

namespace app { namespace automation {

// Measurements use unscaled, in-canvas rendered RGBA pixels. Transparent RGB
// payload is irrelevant visually; any nonzero alpha counts as an occupied pixel.
struct PixelBounds {
  int left = 0, top = 0, right = -1, bottom = -1;
  void add(int x, int y) {
    if (right < left) { left = right = x; top = bottom = y; }
    else {
      left = std::min(left, x); top = std::min(top, y);
      right = std::max(right, x); bottom = std::max(bottom, y);
    }
  }
  nlohmann::json json() const {
    if (right < left) return nullptr;
    return {{"x", left}, {"y", top}, {"width", right - left + 1}, {"height", bottom - top + 1}};
  }
};

struct FrameAnalysis {
  uint64_t visiblePixels = 0, sumX = 0, sumY = 0;
  PixelBounds bounds;
  void add(int x, int y, doc::color_t pixel) {
    if (!doc::rgba_geta(pixel)) return;
    ++visiblePixels; sumX += x; sumY += y; bounds.add(x, y);
  }
  nlohmann::json json() const {
    nlohmann::json centroid = nullptr;
    if (visiblePixels) centroid = {{"x", double(sumX) / visiblePixels}, {"y", double(sumY) / visiblePixels}};
    return {{"visiblePixels", visiblePixels}, {"bounds", bounds.json()}, {"centroid", centroid}};
  }
};

struct FrameDifference {
  uint64_t addedPixels = 0, removedPixels = 0, modifiedPixels = 0, totalPixels = 0;
  PixelBounds bounds;
  FrameAnalysis before, after;
  static doc::color_t addedColor() { return doc::rgba(40, 200, 90, 255); }
  static doc::color_t removedColor() { return doc::rgba(240, 70, 70, 255); }
  static doc::color_t modifiedColor() { return doc::rgba(255, 200, 40, 255); }
  doc::color_t add(int x, int y, doc::color_t from, doc::color_t to) {
    ++totalPixels; before.add(x, y, from); after.add(x, y, to);
    bool fromVisible = doc::rgba_geta(from) != 0, toVisible = doc::rgba_geta(to) != 0;
    if ((!fromVisible && !toVisible) || from == to) return 0;
    bounds.add(x, y);
    if (!fromVisible) { ++addedPixels; return addedColor(); }
    if (!toVisible) { ++removedPixels; return removedColor(); }
    ++modifiedPixels; return modifiedColor();
  }
  nlohmann::json json() const {
    uint64_t changed = addedPixels + removedPixels + modifiedPixels;
    return {{"addedPixels", addedPixels}, {"removedPixels", removedPixels},
            {"modifiedPixels", modifiedPixels}, {"changedPixels", changed},
            {"unchangedPixels", totalPixels - changed}, {"totalPixels", totalPixels},
            {"changedFraction", totalPixels ? double(changed) / totalPixels : 0.0},
            {"bounds", bounds.json()}, {"before", before.json()}, {"after", after.json()}};
  }
};

// Exposure order is supplied by the native tag/frame expansion, not inferred
// from frame numbers. GIF uses the same floored centisecond delays as export.
inline nlohmann::json animationTiming(const std::vector<std::pair<int, int>>& exposures) {
  if (exposures.empty() || exposures.size() > 510)
    throw std::invalid_argument("Provide 1 to 510 playback steps.");
  nlohmann::json steps = nlohmann::json::array(), warnings = nlohmann::json::array();
  int64_t total = 0, gifTotal = 0;
  int minimum = 65535, maximum = 0;
  bool gifExportable = true;
  for (size_t i = 0; i < exposures.size(); ++i) {
    int frame = exposures[i].first, duration = exposures[i].second;
    if (frame < 0 || frame > 255 || duration < 1 || duration > 65535)
      throw std::invalid_argument("Playback steps require frame0-255 and duration1-65535ms.");
    int gifDuration = duration / 10 * 10;
    steps.push_back({{"step", i}, {"frame", frame}, {"durationMs", duration},
                     {"startMs", total}, {"endMs", total + duration}, {"gifDurationMs", gifDuration}});
    if (duration < 10) {
      gifExportable = false;
      warnings.push_back({{"code", "GIF_DELAY_TOO_SHORT"}, {"step", i}, {"frame", frame}, {"durationMs", duration},
                          {"message", "Native GIF export refuses delays below 10ms. APNG preserves this timing."}});
    } else if (duration != gifDuration) {
      warnings.push_back({{"code", "GIF_DELAY_QUANTIZED"}, {"step", i}, {"frame", frame},
                          {"durationMs", duration}, {"gifDurationMs", gifDuration},
                          {"message", "Native GIF export floors this delay to 10ms units; APNG preserves milliseconds."}});
    }
    total += duration; gifTotal += gifDuration;
    minimum = std::min(minimum, duration); maximum = std::max(maximum, duration);
  }
  return {{"steps", steps}, {"warnings", warnings},
          {"summary", {{"stepCount", exposures.size()}, {"totalDurationMs", total},
                       {"minDurationMs", minimum}, {"maxDurationMs", maximum},
                       {"uniformDurations", minimum == maximum}, {"effectiveFps", 1000.0 * exposures.size() / total}}},
          {"gif", {{"exportable", gifExportable}, {"delayQuantumMs", 10},
                   {"encodedTotalDurationMs", gifExportable ? nlohmann::json(gifTotal) : nlohmann::json(nullptr)},
                   {"totalShorteningMs", gifExportable ? nlohmann::json(total - gifTotal) : nlohmann::json(nullptr)}}}};
}

}} // namespace app::automation
