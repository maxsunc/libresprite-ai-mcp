// LibreSprite AI MCP: created 2026-10-01; license notice clarified 2026-10-08.
// Distributed under GNU GPL version 2 only (GPL-2.0-only); see the root LICENSE.
#pragma once

#include <memory>
#include <string>

namespace app {
  // The implementation owns a UI timer and an opt-in local socket. No worker
  // thread is permitted to access documents, commands, or the renderer.
  class AutomationBridge {
  public:
    AutomationBridge(const std::string& socketPath, const std::string& root);
    ~AutomationBridge();
    AutomationBridge(const AutomationBridge&) = delete;
    AutomationBridge& operator=(const AutomationBridge&) = delete;
  private:
    class Impl;
    std::unique_ptr<Impl> m_impl;
  };
}
