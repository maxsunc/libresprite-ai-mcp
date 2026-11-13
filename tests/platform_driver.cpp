// GPL-2.0-only. Assert-based OS boundary checks, independent of the editor GUI.
#include "app/automation/platform_files.h"
#include "app/automation/windows_pipe.h"
#include <cassert>
#include <fstream>
#include <iostream>
#ifdef _WIN32
#include <aclapi.h>
#endif
using namespace app::automation;
std::string contents(const fs::path& path) {
  std::ifstream file(path, std::ios::binary);
  return std::string(std::istreambuf_iterator<char>(file), {});
}
int main(int argc, char** argv) {
  assert(argc == 2);
  auto directory = fs::u8path(argv[1]);
  auto target = directory / fs::u8path("art with spaces-\xc3\xa9.ase");
  fs::path temporary;
  {
    TemporaryFile file(directory, ".ase");
    temporary = file.path();
    file.writeAll({'o', 'l', 'd'});
    assert(file.publish(target, false) == PublishResult::ok);
    assert(contents(target) == "old");
  }
  assert(!fs::exists(temporary));
  {
    TemporaryFile file(directory);
    temporary = file.path();
    file.writeAll({'n', 'e', 'w'});
    assert(file.publish(target, false) == PublishResult::exists);
    assert(contents(target) == "old");
    assert(file.publish(target, true) == PublishResult::ok);
    assert(contents(target) == "new");
  }
  assert(!fs::exists(temporary));
  {
    TemporaryFile failed(directory);
    temporary = failed.path();
    failed.writeAll({'x'});
    assert(failed.publish(directory / "missing/file.ase", false) == PublishResult::error);
    assert(contents(target) == "new");
  }
  assert(!fs::exists(temporary));
  assert(validRelativeAssetPath(fs::u8path("folder/art-\xc3\xa9.ase")));
  assert(validRelativeAssetPath(fs::path("folder/")));
  assert(!validRelativeAssetPath(fs::path("/outside")));
#ifdef _WIN32
  for (auto name : {"C:relative.ase", "C:\\absolute.ase", "\\rooted.ase", "\\\\server\\share\\file", "art.ase:stream", "NUL.png", "sub/COM1.ase", "COM\xc2\xb9.ase", "CONIN$.ase", "foo. ", "foo/bar."})
    assert(!validRelativeAssetPath(fs::u8path(name)));
  std::string name = "\\\\.\\pipe\\libresprite-ai-test-" + std::to_string(GetCurrentProcessId());
  assert(validPipeName(name));
  assert(!validPipeName("\\\\remote\\pipe\\libresprite-ai-test"));
  WindowsPipe pipe(name);
  bool refused = false;
  try { WindowsPipe duplicate(name); } catch (const std::runtime_error&) { refused = true; }
  assert(refused);
  for (int i = 0; i < 2; ++i) {
    assert(!pipe.accept());
    std::wstring wide(name.begin(), name.end());
    HANDLE client = CreateFileW(wide.c_str(), GENERIC_READ | GENERIC_WRITE | READ_CONTROL, 0, nullptr, OPEN_EXISTING, 0, nullptr);
    if (client == INVALID_HANDLE_VALUE) std::cerr << "CreateFile pipe failed: " << GetLastError() << '\n';
    assert(client != INVALID_HANDLE_VALUE);
    assert(pipe.accept());
    PACL acl = nullptr;
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    assert(GetSecurityInfo(client, SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION, nullptr, nullptr, &acl, nullptr, &descriptor) == ERROR_SUCCESS);
    assert(acl && acl->AceCount == 1);
    ACCESS_ALLOWED_ACE* ace = nullptr;
    assert(GetAce(acl, 0, reinterpret_cast<void**>(&ace)));
    assert(ace->Header.AceType == ACCESS_ALLOWED_ACE_TYPE);
    HANDLE token;
    assert(OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token));
    DWORD size = 0;
    GetTokenInformation(token, TokenUser, nullptr, 0, &size);
    std::vector<unsigned char> user(size);
    assert(GetTokenInformation(token, TokenUser, user.data(), size, &size));
    assert(EqualSid(&ace->SidStart, reinterpret_cast<TOKEN_USER*>(user.data())->User.Sid));
    CloseHandle(token); LocalFree(descriptor);
    char buffer[8]; DWORD count;
    assert(pipe.read(buffer, sizeof(buffer)) == -1);
    assert(WriteFile(client, "abc", 3, &count, nullptr) && count == 3);
    assert(pipe.read(buffer, sizeof(buffer)) == 3);
    assert(std::string(buffer, 3) == "abc");
    assert(pipe.write("xyz", 3) == 3);
    assert(ReadFile(client, buffer, sizeof(buffer), &count, nullptr) && count == 3);
    assert(std::string(buffer, 3) == "xyz");
    std::vector<char> large(256 * 1024, 'x');
    size_t queued = 0;
    int attempts = 0;
    for (; attempts < 16; ++attempts) {
      int sent = pipe.write(large.data(), large.size());
      if (sent < 0) break;
      queued += size_t(sent);
    }
    assert(attempts < 16 && queued > 0); // Backpressure must not block the UI.
    while (queued) {
      assert(ReadFile(client, large.data(), DWORD(std::min(large.size(), queued)), &count, nullptr) && count > 0);
      queued -= count;
    }
    CloseHandle(client);
    bool broken = false;
    try { pipe.read(buffer, sizeof(buffer)); } catch (const std::runtime_error&) { broken = true; }
    assert(broken);
    pipe.disconnect();
  }
#endif
  fs::remove(target);
}
