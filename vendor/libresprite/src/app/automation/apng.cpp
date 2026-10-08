// LibreSprite AI MCP: created 2026-10-01; license notice clarified 2026-10-08.
// Distributed under GNU GPL version 2 only (GPL-2.0-only); see the root LICENSE.
#include "app/automation/apng.h"

#include <algorithm>
#include <stdexcept>
#include <utility>
#include <zlib.h>

namespace app {
namespace automation {
namespace {
constexpr size_t MaxBytes = 32 * 1024 * 1024;
const std::vector<uint8_t> Signature{137, 80, 78, 71, 13, 10, 26, 10};
void check(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
uint32_t word(const uint8_t* data) {
  return (uint32_t(data[0]) << 24) | (uint32_t(data[1]) << 16) |
         (uint32_t(data[2]) << 8) | data[3];
}
void putWord(std::vector<uint8_t>& data, uint32_t value) {
  for (int shift = 24; shift >= 0; shift -= 8) data.push_back(uint8_t(value >> shift));
}
}
ApngEncoder::ApngEncoder(unsigned frames, bool loop)
  : m_output(Signature), m_frames(frames), m_loop(loop) {
  check(frames > 0 && frames <= 510, "Invalid APNG frame count.");
}
void ApngEncoder::chunk(const char* type, const std::vector<uint8_t>& payload) {
  if (payload.size() > MaxBytes || m_output.size() + payload.size() + 12 > MaxBytes)
    throw std::length_error("APNG exceeds the 32 MiB encoded-file limit.");
  putWord(m_output, uint32_t(payload.size()));
  auto start = m_output.size();
  m_output.insert(m_output.end(), type, type + 4);
  m_output.insert(m_output.end(), payload.begin(), payload.end());
  putWord(m_output, uint32_t(crc32(0, m_output.data() + start, uInt(payload.size() + 4))));
}
void ApngEncoder::append(const std::vector<uint8_t>& png, unsigned durationMs) {
  check(m_written < m_frames && durationMs >= 1 && durationMs <= 65535,
        "Invalid APNG frame or duration.");
  check(png.size() >= 33 && std::equal(Signature.begin(), Signature.end(), png.begin()),
        "Native encoder did not produce a PNG.");
  bool header = false, data = false, end = false;
  size_t offset = 8;
  while (offset + 12 <= png.size()) {
    auto size = word(png.data() + offset);
    check(size <= png.size() - offset - 12, "Truncated native PNG chunk.");
    auto type = png.data() + offset + 4;
    check(word(png.data() + offset + 8 + size) == crc32(0, type, uInt(size + 4)),
          "Invalid native PNG checksum.");
    std::vector<uint8_t> payload(png.begin() + offset + 8, png.begin() + offset + 8 + size);
    if (std::equal(type, type + 4, "IHDR")) {
      check(!header && offset == 8 && size == 13 && payload[8] == 8 && payload[9] == 6 &&
            payload[10] == 0 && payload[11] == 0 && payload[12] == 0,
            "APNG requires native non-interlaced 8-bit RGBA PNG frames.");
      check(word(payload.data()) > 0 && word(payload.data() + 4) > 0 &&
            uint64_t(word(payload.data())) * word(payload.data() + 4) <= 1048576,
            "Invalid or oversized APNG canvas.");
      if (m_written == 0) {
        m_header = payload;
        chunk("IHDR", payload);
        std::vector<uint8_t> animation;
        putWord(animation, m_frames); putWord(animation, m_loop ? 0 : 1);
        chunk("acTL", animation);
      } else check(payload == m_header, "APNG frame dimensions/formats differ.");
      std::vector<uint8_t> control;
      putWord(control, m_sequence++);
      control.insert(control.end(), payload.begin(), payload.begin() + 8); // Width/height
      putWord(control, 0); putWord(control, 0); // x/y
      control.push_back(uint8_t(durationMs >> 8)); control.push_back(uint8_t(durationMs));
      control.push_back(3); control.push_back(232); // denominator 1000
      control.push_back(0); control.push_back(0); // dispose NONE, blend SOURCE
      chunk("fcTL", control);
      header = true;
    } else if (std::equal(type, type + 4, "IDAT")) {
      check(header && !end, "Invalid PNG image-data order.");
      if (m_written == 0) chunk("IDAT", payload);
      else {
        std::vector<uint8_t> frameData;
        putWord(frameData, m_sequence++);
        frameData.insert(frameData.end(), payload.begin(), payload.end());
        chunk("fdAT", frameData);
      }
      data = true;
    } else if (std::equal(type, type + 4, "IEND")) {
      check(header && data && size == 0, "Invalid PNG end chunk.");
      end = true;
    }
    offset += size + 12;
    if (end) break;
  }
  check(end && offset == png.size(), "Incomplete native PNG.");
  ++m_written;
}
std::vector<uint8_t> ApngEncoder::finish() {
  check(m_written == m_frames, "Incomplete APNG animation.");
  chunk("IEND", {});
  return std::move(m_output);
}
}
}
