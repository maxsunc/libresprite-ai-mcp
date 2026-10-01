// Aseprite Document Library
// Copyright (c) 2001-2015 David Capello
//
// This file is released under the terms of the MIT license.
// Read LICENSE.txt for more information.

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include "doc/layers_range.h"

#include "doc/cel.h"
#include "doc/layer.h"
#include "doc/sprite.h"

namespace doc {

LayersRange::LayersRange(const Sprite* sprite,
                         LayerIndex first, LayerIndex last)
  : m_begin(sprite, first, last)
  , m_end()
{
}

LayersRange::iterator::iterator()
  : m_sprite(nullptr)
  , m_layer(nullptr)
  , m_cur(-1)
  , m_last(-1)
{
}

LayersRange::iterator::iterator(const Sprite* sprite,
                                LayerIndex first, LayerIndex last)
  : m_sprite(sprite)
  , m_layer(nullptr)
  , m_cur(first)
  , m_last(last)
{
  m_layer = sprite->layer(first);
}

LayersRange::iterator& LayersRange::iterator::operator++()
{
  if (!m_layer)
    return *this;

  ++m_cur;
  if (m_cur > m_last)
    m_layer = nullptr;
  else
    // getNext() only walks siblings and would silently omit group children.
    m_layer = m_sprite->indexToLayer(m_cur);

  return *this;
}

} // namespace doc
