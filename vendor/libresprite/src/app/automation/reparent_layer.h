// LibreSprite AI MCP, 2026-10-08. GPL-2.0-only; see the root LICENSE.
#pragma once
#include "app/cmd.h"
#include "app/cmd/with_layer.h"
namespace doc { class LayerFolder; }

namespace app { namespace automation {
// Targets/cycles/locks must be validated before constructing this command.
class ReparentLayer : public Cmd {
public:
  ReparentLayer(doc::Layer* layer, doc::LayerFolder* parent, doc::Layer* after);
protected:
  void onExecute() override;
  void onUndo() override;
  void onFireNotifications() override;
  size_t onMemSize() const override { return sizeof(*this); }
private:
  void move(doc::LayerFolder* parent, doc::Layer* after);
  cmd::WithLayer m_layer, m_oldParent, m_newParent, m_oldAfter, m_newAfter;
};
} }
