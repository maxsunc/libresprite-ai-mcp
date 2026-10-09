// LibreSprite AI MCP, 2026-10-08. GPL-2.0-only; see the root LICENSE.
#pragma once
#include "../../../../nlohmann/json.hpp"

namespace app { namespace automation {
inline nlohmann::json revisionMetadata(const nlohmann::json& metadata) {
  auto result = metadata;
  // crash::Writer::saveObject initializes zero versions to one without edits.
  // Canonicalize ONLY that bookkeeping transition; keep higher counters and
  // all actual properties/identities. Pixel bytes and undo state are also
  // independently included in the bridge's revision fingerprint.
  for (auto& layer : result["layers"]) {
    if (layer["version"] == 0) layer["version"] = 1;
    if (layer.contains("cels")) for (auto& cel : layer["cels"])
      if (cel["imageVersion"] == 0) cel["imageVersion"] = 1;
  }
  return result;
}
} }
