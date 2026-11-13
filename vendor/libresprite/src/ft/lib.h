// Aseprite FreeType Wrapper
// Copyright (c) 2016 David Capello
// LibreSprite AI contributors: modified 2026-11-12 for UTF-8 Windows font paths.
//
// This file is released under the terms of the MIT license.
// Read LICENSE.txt for more information.

#pragma once

#include "base/disable_copying.h"
#include "ft/freetype_headers.h"

#include <string>
#ifdef _WIN32
#include "base/file_handle.h"
#include <list>
#include <vector>
#endif

namespace ft {

  class Lib {
  public:
    Lib() : m_ft(nullptr) {
      FT_Init_FreeType(&m_ft);
    }

    ~Lib() {
      if (m_ft)
        FT_Done_FreeType(m_ft);
    }

    operator FT_Library() {
      return m_ft;
    }

    FT_Face open(const std::string& filename) {
#ifdef _WIN32
      // FreeType's pathname API is ANSI; keep UTF-8-opened bytes alive with the library.
      auto file = base::open_file(filename, "rb");
      if (!file || fseek(file.get(), 0, SEEK_END) != 0) return nullptr;
      auto size = ftell(file.get());
      if (size <= 0 || fseek(file.get(), 0, SEEK_SET) != 0) return nullptr;
      m_fonts.emplace_back(size);
      auto& bytes = m_fonts.back();
      if (fread(bytes.data(), 1, bytes.size(), file.get()) != bytes.size()) {
        m_fonts.pop_back(); return nullptr;
      }
      FT_Face face = nullptr;
      FT_Error err = FT_New_Memory_Face(m_ft, bytes.data(), FT_Long(bytes.size()), 0, &face);
      if (err) m_fonts.pop_back();
#else
      FT_Open_Args args;
      memset(&args, 0, sizeof(args));
      args.flags = FT_OPEN_PATHNAME;
      args.pathname = (FT_String*)filename.c_str();

      FT_Face face = nullptr;
      FT_Error err = FT_Open_Face(m_ft, &args, 0, &face);
#endif
      if (!err)
        FT_Select_Charmap(face, FT_ENCODING_UNICODE);
      return face;
    }

  private:
    FT_Library m_ft;
#ifdef _WIN32
    std::list<std::vector<FT_Byte>> m_fonts;
#endif

    DISABLE_COPYING(Lib);
  };

} // namespace ft
