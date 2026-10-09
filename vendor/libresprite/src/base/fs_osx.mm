// Aseprite Base Library
// Copyright (c) 2016 David Capello
//
// This file is released under the terms of the MIT license.
// Read LICENSE.txt for more information.

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include <Foundation/Foundation.h>

#include <string>
#include <vector>

namespace base {

// LibreSprite AI MCP: added 2026-10-08; existing MIT terms retained.
std::string get_app_bundle_id()
{
  NSString* identifier = [[NSBundle mainBundle] bundleIdentifier];
  return identifier ? std::string([identifier UTF8String]) : std::string();
}

std::string get_lib_app_support_path()
{
  NSArray* dirs = NSSearchPathForDirectoriesInDomains(
    NSApplicationSupportDirectory, NSUserDomainMask, YES);
  if (dirs) {
    NSString* dir = [dirs firstObject];
    if (dir)
      return std::string([dir UTF8String]);
  }
  return std::string();
}

std::vector<std::string> get_font_paths()
{
    return {
        "/System/Library/Fonts/Supplemental",
        "/System/Library/Fonts",
        "/Library/Fonts",
        "~/Library/Fonts"
    };
}

} // namespace base
