// LibreSprite AI contributors, created 2026-11-12. GPL-2.0-only.
// Local, current-user-only byte pipe; all GUI-thread I/O is nonblocking.
#ifndef APP_AUTOMATION_WINDOWS_PIPE_H_INCLUDED
#define APP_AUTOMATION_WINDOWS_PIPE_H_INCLUDED
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <sddl.h>
#include <algorithm>
#include <stdexcept>
#include <string>
#include <vector>

namespace app { namespace automation {
inline bool validPipeName(const std::string& name) {
  const std::string prefix = "\\\\.\\pipe\\libresprite-ai-";
  if (name.compare(0, prefix.size(), prefix) != 0 || name.size() <= prefix.size() || name.size() > prefix.size() + 100) return false;
  return std::all_of(name.begin() + prefix.size(), name.end(), [](unsigned char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' || c == '_';
  });
}

class WindowsPipe {
public:
  explicit WindowsPipe(const std::string& name) {
    if (!validPipeName(name)) throw std::runtime_error("Invalid local automation pipe name.");
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) throw std::runtime_error("Cannot query current user.");
    DWORD size = 0;
    GetTokenInformation(token, TokenUser, nullptr, 0, &size);
    std::vector<unsigned char> info(size);
    bool ok = size && GetTokenInformation(token, TokenUser, info.data(), size, &size);
    CloseHandle(token);
    if (!ok) throw std::runtime_error("Cannot query current user SID.");
    LPWSTR sid = nullptr;
    if (!ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(info.data())->User.Sid, &sid)) throw std::runtime_error("Cannot encode current user SID.");
    // Protected DACL: no inherited Everyone/Users permissions, only this user.
    std::wstring acl = std::wstring(L"D:P(A;;GA;;;") + sid + L")";
    LocalFree(sid);
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(acl.c_str(), SDDL_REVISION_1, &descriptor, nullptr)) throw std::runtime_error("Cannot secure automation pipe.");
    SECURITY_ATTRIBUTES security = {sizeof(SECURITY_ATTRIBUTES), descriptor, FALSE};
    std::wstring wide(name.begin(), name.end());
    m_pipe = CreateNamedPipeW(wide.c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
      PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_NOWAIT | PIPE_REJECT_REMOTE_CLIENTS,
      1, 256 * 1024, 256 * 1024, 0, &security);
    LocalFree(descriptor);
    if (m_pipe == INVALID_HANDLE_VALUE) throw std::runtime_error("Cannot create automation pipe; the endpoint may already belong to another editor.");
  }
  ~WindowsPipe() { CloseHandle(m_pipe); }
  WindowsPipe(const WindowsPipe&) = delete;
  WindowsPipe& operator=(const WindowsPipe&) = delete;

  bool accept() {
    if (ConnectNamedPipe(m_pipe, nullptr)) return true;
    auto error = GetLastError();
    if (error == ERROR_PIPE_CONNECTED) return true;
    if (error == ERROR_NO_DATA) { disconnect(); return false; }
    if (error == ERROR_PIPE_LISTENING) return false;
    throw std::runtime_error("Cannot accept automation client.");
  }
  void disconnect() { DisconnectNamedPipe(m_pipe); }
  // Return -1 for backpressure/no input; throw only on a broken connection.
  int read(char* data, size_t size) {
    DWORD count = 0;
    if (ReadFile(m_pipe, data, DWORD(size), &count, nullptr)) return count ? int(count) : -1;
    if (GetLastError() == ERROR_NO_DATA) return -1;
    throw std::runtime_error("Automation pipe disconnected during read.");
  }
  int write(const char* data, size_t size) {
    DWORD count = 0;
    if (WriteFile(m_pipe, data, DWORD(size), &count, nullptr)) return count ? int(count) : -1;
    if (GetLastError() == ERROR_NO_DATA || GetLastError() == ERROR_PIPE_BUSY) return -1;
    throw std::runtime_error("Automation pipe disconnected during write.");
  }
private:
  HANDLE m_pipe = INVALID_HANDLE_VALUE;
};
}}
#endif
#endif
