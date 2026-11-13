// LibreSprite AI contributors, created 2026-11-12. GPL-2.0-only.
// Exclusive sibling temporaries and atomic publication on each OS.
#ifndef APP_AUTOMATION_PLATFORM_FILES_H_INCLUDED
#define APP_AUTOMATION_PLATFORM_FILES_H_INCLUDED
#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <filesystem>
#include <iomanip>
#include <random>
#include <sstream>
#include <string>
#include <vector>
#include <fcntl.h>
#include <sys/stat.h>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <io.h>
#else
#include <unistd.h>
#endif

namespace app { namespace automation {
namespace fs = std::filesystem;
inline std::string utf8Path(const fs::path& path) {
  auto bytes = path.generic_u8string();
  return std::string(bytes.begin(), bytes.end());
}
// MinGW filesystem::canonical can leave Windows junctions unresolved.
inline fs::path canonicalPath(const fs::path& path) {
#ifdef _WIN32
  HANDLE file = CreateFileW(path.c_str(), 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
    nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr);
  if (file == INVALID_HANDLE_VALUE) throw fs::filesystem_error("Cannot resolve asset path", path, std::error_code(GetLastError(), std::system_category()));
  std::vector<wchar_t> buffer(32768);
  DWORD size = GetFinalPathNameByHandleW(file, buffer.data(), DWORD(buffer.size()), FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
  auto error = GetLastError();
  CloseHandle(file);
  if (!size || size >= buffer.size()) throw fs::filesystem_error("Cannot resolve asset path", path, std::error_code(error, std::system_category()));
  std::wstring name(buffer.data(), size);
  if (name.compare(0, 8, L"\\\\?\\UNC\\") == 0) name = L"\\\\" + name.substr(8);
  else if (name.compare(0, 4, L"\\\\?\\") == 0) name.erase(0, 4);
  return fs::path(name);
#else
  return fs::canonical(path);
#endif
}
inline bool isLink(const fs::path& path) {
#ifdef _WIN32
  DWORD attributes = GetFileAttributesW(path.c_str());
  return attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_REPARSE_POINT);
#else
  return fs::is_symlink(fs::symlink_status(path));
#endif
}
inline bool validRelativeAssetPath(const fs::path& path) {
  if (path.empty() || path.has_root_name() || path.has_root_directory()) return false;
#ifdef _WIN32
  for (const auto& part : path) {
    auto name = utf8Path(part);
    if (name.empty() || name == "." || name == "..") continue;
    if (name.back() == '.' || name.back() == ' ' ||
        name.find_first_of(":*?\"<>|") != std::string::npos ||
        std::any_of(name.begin(), name.end(), [](unsigned char c) { return c < 32; })) return false;
    auto stem = name.substr(0, name.find('.'));
    for (auto& c : stem) if (c >= 'a' && c <= 'z') c -= 'a' - 'A';
    if (stem == "CON" || stem == "PRN" || stem == "AUX" || stem == "NUL" || stem == "CONIN$" || stem == "CONOUT$") return false;
    if (stem.substr(0, 3) == "COM" || stem.substr(0, 3) == "LPT") {
      auto number = stem.substr(3);
      if ((number.size() == 1 && number[0] >= '1' && number[0] <= '9') ||
          number == "\xc2\xb9" || number == "\xc2\xb2" || number == "\xc2\xb3") return false;
    }
  }
#endif
  return true;
}

enum class PublishResult { ok, exists, error };
class TemporaryFile {
public:
  TemporaryFile(const fs::path& directory, const std::string& suffix = "") {
    std::random_device random;
    for (int attempt = 0; attempt < 16; ++attempt) {
      std::ostringstream name;
      name << ".libresprite-ai-" << std::hex << std::setfill('0');
      for (int i = 0; i < 4; ++i) name << std::setw(8) << random();
      m_path = directory / (name.str() + suffix);
#ifdef _WIN32
      m_fd = _wopen(m_path.c_str(), _O_CREAT | _O_EXCL | _O_RDWR | _O_BINARY | _O_NOINHERIT, _S_IREAD | _S_IWRITE);
#else
      m_fd = open(m_path.c_str(), O_CREAT | O_EXCL | O_RDWR | O_CLOEXEC, 0600);
#endif
      if (m_fd >= 0) return;
      if (errno != EEXIST) break;
    }
    fail("Cannot create exclusive temporary file");
  }
  ~TemporaryFile() {
    if (m_fd >= 0) closeFd(m_fd);
    std::error_code error;
    fs::remove(m_path, error);
  }
  TemporaryFile(const TemporaryFile&) = delete;
  TemporaryFile& operator=(const TemporaryFile&) = delete;
  const fs::path& path() const { return m_path; }
  std::string name() const { return utf8Path(m_path); }
  void finish() {
    if (m_fd < 0) return;
    int fd = m_fd; m_fd = -1;
    if (closeFd(fd) != 0) fail("Cannot finish temporary file");
  }
  void writeAll(const std::vector<uint8_t>& bytes) {
    size_t written = 0;
    while (written < bytes.size()) {
      auto size = std::min(size_t(256 * 1024), bytes.size() - written);
#ifdef _WIN32
      auto count = _write(m_fd, bytes.data() + written, unsigned(size));
#else
      auto count = write(m_fd, bytes.data() + written, size);
#endif
      if (count < 0 && errno == EINTR) continue;
      if (count <= 0) fail("Cannot write temporary file");
      written += size_t(count);
    }
    finish();
  }
  PublishResult publish(const fs::path& target, bool overwrite) {
    finish();
#ifdef _WIN32
    if (MoveFileExW(m_path.c_str(), target.c_str(), MOVEFILE_WRITE_THROUGH | (overwrite ? MOVEFILE_REPLACE_EXISTING : 0))) return PublishResult::ok;
    auto error = GetLastError();
    return error == ERROR_FILE_EXISTS || error == ERROR_ALREADY_EXISTS ? PublishResult::exists : PublishResult::error;
#else
    if (overwrite) { fs::rename(m_path, target); return PublishResult::ok; }
    if (link(m_path.c_str(), target.c_str()) == 0) return PublishResult::ok;
    return errno == EEXIST ? PublishResult::exists : PublishResult::error;
#endif
  }
private:
  fs::path m_path;
  int m_fd = -1;
  static int closeFd(int fd) {
#ifdef _WIN32
    return _close(fd);
#else
    return close(fd);
#endif
  }
  [[noreturn]] void fail(const char* message) const {
    throw fs::filesystem_error(message, m_path, std::error_code(errno, std::generic_category()));
  }
};
}}
#endif
