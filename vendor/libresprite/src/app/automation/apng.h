// LibreSprite AI MCP: created 2026-10-01; license notice clarified 2026-10-08.
// Distributed under GNU GPL version 2 only (GPL-2.0-only); see the root LICENSE.
#pragma once

#include <cstdint>
#include <vector>

namespace app {
namespace automation {
// Full-canvas RGBA APNG assembly from the existing native PNG encoder.
// No GUI/document state is involved; frames replace rather than blend pixels.
class ApngEncoder {
public:
  ApngEncoder(unsigned frames, bool loop);
  void append(const std::vector<uint8_t>& png, unsigned durationMs);
  std::vector<uint8_t> finish();
private:
  void chunk(const char* type, const std::vector<uint8_t>& payload);
  std::vector<uint8_t> m_output, m_header;
  unsigned m_frames, m_written = 0, m_sequence = 0;
  bool m_loop;
};
}
}
