// Modified by LibreSprite AI MCP contributors, 2026-10-01: nested-group cel traversal.
// Modification notice added 2026-10-08; original upstream MIT notices below are retained.
// Aseprite Document Library
// Copyright (c) 2001-2015 David Capello
//
// This file is released under the terms of the MIT license.
// Read LICENSE.txt for more information.

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include "doc/cels_range.h"

#include "doc/cel.h"
#include "doc/layer.h"
#include "doc/sprite.h"

namespace doc {

CelsRange::CelsRange(const Sprite* sprite,
  frame_t first, frame_t last, Flags flags)
  : m_begin(sprite, first, last, flags)
  , m_end()
{
}

CelsRange::iterator::iterator()
  : m_sprite(nullptr)
  , m_layerIndex(-1)
  , m_cel(nullptr)
{
}

CelsRange::iterator::iterator(const Sprite* sprite, frame_t first, frame_t last, CelsRange::Flags flags)
  : m_sprite(sprite)
  , m_layerIndex(0)
  , m_cel(nullptr)
  , m_first(first)
  , m_last(last)
  , m_flags(flags)
{
  // Get first cel
  for (; m_layerIndex < sprite->countLayers(); ++m_layerIndex) {
    Layer* layer = sprite->layer(m_layerIndex);
    for (frame_t f=first; f<=last; ++f) {
      m_cel = layer->cel(f);
      if (m_cel)
        break;
      m_cel = nullptr;
    }
    if (m_cel) break;
  }
  if (m_cel && flags == CelsRange::UNIQUE)
    m_visited.insert(m_cel->data()->id());
}

CelsRange::iterator& CelsRange::iterator::operator++()
{
  if (!m_cel)
    return *this;

  // Get next cel
  frame_t first = m_cel->frame()+1;
  m_cel = nullptr;

  for (; m_layerIndex < m_sprite->countLayers(); ++m_layerIndex) {
    Layer* layer = m_sprite->layer(m_layerIndex);
    for (frame_t f=first; f<=m_last; ++f) {
      m_cel = layer->cel(f);
      if (m_cel) {
        if (m_flags == CelsRange::UNIQUE) {
          if (m_visited.find(m_cel->data()->id()) == m_visited.end()) {
            m_visited.insert(m_cel->data()->id());
            break;
          }
          else
            m_cel = nullptr;
        }
        else
          break;
      }
    }
    if (m_cel) break;
    first = m_first;
  }
  return *this;
}

} // namespace doc
