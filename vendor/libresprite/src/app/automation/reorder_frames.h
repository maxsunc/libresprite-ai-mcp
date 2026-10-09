// LibreSprite AI MCP, 2026-10-08. GPL-2.0-only; see the root LICENSE.
#pragma once
#include "app/cmd.h"
#include "app/cmd/with_sprite.h"
#include <vector>

namespace app { namespace automation {
// Native undoable permutation, preserving cel/image/data identities and links.
// newToOld must be a validated permutation of all current frame indices.
class ReorderFrames : public Cmd, public cmd::WithSprite {
public:
  ReorderFrames(doc::Sprite* sprite, const std::vector<int>& newToOld);
protected:
  void onExecute() override;
  void onUndo() override;
  void onFireNotifications() override;
  size_t onMemSize() const override;
private:
  void apply(const std::vector<int>& oldToNew);
  std::vector<int> m_oldToNew, m_newToOld;
};
} }
