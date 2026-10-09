// LibreSprite AI MCP, 2026-10-08. GPL-2.0-only; see the root LICENSE.
#include "app/automation/reorder_frames.h"
#include "app/document.h"
#include "doc/cel.h"
#include "doc/layer.h"
#include "doc/layers_range.h"
#include "doc/sprite.h"
#include <stdexcept>

namespace app { namespace automation {
ReorderFrames::ReorderFrames(doc::Sprite* sprite, const std::vector<int>& order)
  : WithSprite(sprite), m_oldToNew(order.size(), -1), m_newToOld(order) {
  if (order.size() != size_t(sprite->totalFrames())) throw std::invalid_argument("Frame permutation must include every frame.");
  for (size_t i = 0; i < order.size(); ++i) {
    if (order[i] < 0 || size_t(order[i]) >= order.size() || m_oldToNew[order[i]] != -1)
      throw std::invalid_argument("Frame permutation must contain unique valid indices.");
    m_oldToNew[order[i]] = i;
  }
}
void ReorderFrames::apply(const std::vector<int>& mapping) {
  auto spr = sprite();
  struct LayerCels { doc::LayerImage* layer; doc::CelList cels; };
  std::vector<LayerCels> layers;
  std::vector<int> durations;
  // All allocating preparation happens before touching the model. LayerImage's
  // vectors retain capacity during erase/reinsert, so reattachment allocates no
  // new slots. Snapshot on EVERY execution: undo of a later layer deletion may
  // have recreated its objects, so retaining raw pointers across history is unsafe.
  for (auto layer : spr->layers()) if (layer->isImage()) {
    LayerCels item{static_cast<doc::LayerImage*>(layer), {}};
    item.layer->getCels(item.cels);
    layers.push_back(std::move(item));
  }
  for (int i = 0; i < spr->totalFrames(); ++i) durations.push_back(spr->frameDuration(i));
  for (auto& item : layers) {
    // Never move into an occupied frame: the legacy layer removes by frame,
    // not by pointer, and transient collisions could remove the wrong cel.
    for (auto cel : item.cels) item.layer->removeCel(cel);
    for (auto cel : item.cels) {
      cel->setFrame(mapping[cel->frame()]);
      item.layer->addCel(cel);
      cel->incrementVersion();
    }
  }
  for (size_t i = 0; i < mapping.size(); ++i) spr->setFrameDuration(mapping[i], durations[i]);
  spr->incrementVersion();
}
void ReorderFrames::onExecute() { apply(m_oldToNew); }
void ReorderFrames::onUndo() { apply(m_newToOld); }
void ReorderFrames::onFireNotifications() { static_cast<Document*>(sprite()->document())->notifyGeneralUpdate(); }
size_t ReorderFrames::onMemSize() const { return sizeof(*this) + (m_oldToNew.size() + m_newToOld.size()) * sizeof(int); }
} }
