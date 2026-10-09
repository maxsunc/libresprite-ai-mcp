// LibreSprite AI MCP, 2026-10-08. GPL-2.0-only; see the root LICENSE.
#include "app/automation/reparent_layer.h"
#include "doc/document.h"
#include "doc/document_event.h"
#include "doc/layer.h"
#include "doc/sprite.h"

namespace app { namespace automation {
ReparentLayer::ReparentLayer(doc::Layer* layer, doc::LayerFolder* parent, doc::Layer* after)
  : m_layer(layer), m_oldParent(layer->parent()), m_newParent(parent),
    m_oldAfter(layer->getPrevious()), m_newAfter(after) {}
void ReparentLayer::move(doc::LayerFolder* parent, doc::Layer* after) {
  auto layer = m_layer.layer();
  auto previous = layer->parent();
  // The only allocating operation comes FIRST. There are no observers between
  // attaching to the destination and removing from the source. A failed vector
  // allocation therefore leaves the original hierarchy intact.
  parent->addLayer(layer);
  previous->removeLayer(layer);
  layer->setParent(parent);
  parent->stackLayer(layer, after);
  previous->incrementVersion(); parent->incrementVersion();
}
void ReparentLayer::onExecute() { move(static_cast<doc::LayerFolder*>(m_newParent.layer()), m_newAfter.layer()); }
void ReparentLayer::onUndo() { move(static_cast<doc::LayerFolder*>(m_oldParent.layer()), m_oldAfter.layer()); }
void ReparentLayer::onFireNotifications() {
  auto layer = m_layer.layer();
  doc::DocumentEvent event(layer->sprite()->document());
  event.sprite(layer->sprite()); event.layer(layer);
  layer->sprite()->document()->notifyObservers<doc::DocumentEvent&>(&doc::DocumentObserver::onLayerRestacked, event);
}
} }
