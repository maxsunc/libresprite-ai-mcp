// LibreSprite AI MCP: created 2026-10-01; license notice clarified 2026-10-08.
// Distributed under GNU GPL version 2 only (GPL-2.0-only); see the root LICENSE.
// Updated 2026-10-08: visible user controls and guarded document/site navigation.
// Updated 2026-10-08: independent cel copies and atomic animation-range editing.
// Updated 2026-10-08: guarded canvas/layer operations, masks, brushes/index painting.
#include "app/automation/bridge.h"

#if defined(__APPLE__) || defined(__linux__)
#include "app/app.h"
#include "app/automation/apng.h"
#include "app/automation/reorder_frames.h"
#include "app/automation/reparent_layer.h"
#include "app/automation/revision_metadata.h"
#include "app/cmd/add_cel.h"
#include "app/cmd/add_frame_tag.h"
#include "app/cmd/add_layer.h"
#include "app/cmd/add_palette.h"
#include "app/cmd/copy_cel.h"
#include "app/cmd/move_layer.h"
#include "app/cmd/patch_cel.h"
#include "app/cmd/remove_layer.h"
#include "app/cmd/remove_frame_tag.h"
#include "app/cmd/remove_palette.h"
#include "app/cmd/remove_cel.h"
#include "app/cmd/replace_image.h"
#include "app/cmd/set_cel_opacity.h"
#include "app/cmd/set_cel_position.h"
#include "app/cmd/set_frame_duration.h"
#include "app/cmd/set_frame_tag_anidir.h"
#include "app/cmd/set_frame_tag_color.h"
#include "app/cmd/set_frame_tag_name.h"
#include "app/cmd/set_frame_tag_range.h"
#include "app/cmd/set_layer_flags.h"
#include "app/cmd/set_layer_name.h"
#include "app/cmd/set_layer_opacity.h"
#include "app/cmd/set_layer_blend_mode.h"
#include "app/cmd/set_sprite_size.h"
#include "app/cmd/set_mask_position.h"
#include "app/cmd/set_palette.h"
#include "app/cmd/set_mask.h"
#include "app/cmd/unlink_cel.h"
#include "app/context_access.h"
#include "app/document_api.h"
#include "app/document_undo.h"
#include "app/file/file.h"
#include "app/file/gif_options.h"
#include "app/modules/editors.h"
#include "app/modules/gui.h"
#include "app/modules/palettes.h"
#include "app/transaction.h"
#include "app/ui/editor/editor.h"
#include "app/ui/editor/standby_state.h"
#include "app/ui/document_view.h"
#include "app/ui/main_window.h"
#include "app/ui/status_bar.h"
#include "app/ui_context.h"
#include "base/base64.h"
#include "base/sha1_rfc3174.h"
#include "doc/cel.h"
#include "doc/cels_range.h"
#include "doc/algorithm/floodfill.h"
#include "doc/algorithm/flip_image.h"
#include "doc/blend_funcs.h"
#include "doc/documents.h"
#include "doc/frame_tag.h"
#include "doc/image.h"
#include "doc/layer.h"
#include "doc/layers_range.h"
#include "doc/mask.h"
#include "doc/palette.h"
#include "doc/primitives.h"
#include "doc/sprite.h"
#include "render/render.h"
#include "she/surface.h"
#include "she/system.h"
#include "ui/manager.h"
#include "ui/button.h"
#include "ui/tooltips.h"
#include "ui/timer.h"
#include "../../../../nlohmann/json.hpp"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <map>
#include <random>
#include <sstream>
#include <stdexcept>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

namespace app {
namespace {
using Json = nlohmann::json;
namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
constexpr size_t MaxRequest = 1024 * 1024;
constexpr size_t MaxResponse = 8 * 1024 * 1024;
constexpr size_t MaxPixels = 1024 * 1024;
constexpr size_t MaxAnimationPixels = 8 * 1024 * 1024;

struct BridgeError : std::runtime_error {
  std::string code;
  BridgeError(const std::string& code, const std::string& message)
    : std::runtime_error(message), code(code) {}
};
void require(bool condition, const std::string& code, const std::string& message) {
  if (!condition) throw BridgeError(code, message);
}
int integer(const Json& object, const char* key, int low, int high) {
  require(object.contains(key) && object[key].is_number_integer(), "INVALID_PARAMS", std::string(key) + " must be an integer.");
  auto value = object[key].get<int64_t>();
  require(value >= low && value <= high, "INVALID_PARAMS", std::string(key) + " is out of range.");
  return int(value);
}
std::string text(const Json& object, const char* key, size_t limit = 4096) {
  require(object.contains(key) && object[key].is_string(), "INVALID_PARAMS", std::string(key) + " must be a string.");
  auto value = object[key].get<std::string>();
  require(!value.empty() && value.size() <= limit && value.find('\0') == std::string::npos, "INVALID_PARAMS", std::string(key) + " is empty or too long.");
  return value;
}
bool boolean(const Json& object, const char* key) {
  require(object.contains(key) && object[key].is_boolean(), "INVALID_PARAMS", std::string(key) + " must be boolean.");
  return object[key].get<bool>();
}
color_t color(const Json& params) {
  require(params.contains("color") && params["color"].is_object(), "INVALID_PARAMS", "color must contain r, g, b, and a.");
  const auto& value = params["color"];
  return rgba(integer(value, "r", 0, 255), integer(value, "g", 0, 255), integer(value, "b", 0, 255), integer(value, "a", 0, 255));
}
Layer* findLayer(Sprite* sprite, int id) {
  for (auto layer : sprite->layers()) if (layer->id() == ObjectId(id)) return layer;
  throw BridgeError("LAYER_NOT_FOUND", "Layer no longer exists in this document.");
}
void editable(Layer* target) {
  for (auto layer = target; layer; layer = layer->parent())
    require(layer->isEditable(), "LAYER_LOCKED", "Target layer or its parent is locked.");
}
void workingLimits(Document* document) {
  std::vector<Image*> images;
  document->sprite()->getImages(images);
  size_t total = 0;
  for (auto image : images) {
    total += size_t(image->getRowStrideSize()) * size_t(image->height());
    require(total <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Sprite image data exceeds the bridge's 32 MiB working limit.");
  }
}
// Native structural commands can change editor selection during execution.
// On rollback restore IDs, not potentially deleted/recreated layer pointers.
class SelectionGuard {
public:
  explicit SelectionGuard(Document* document)
    : m_document(document), m_mask(new Mask(*document->mask())),
      m_maskVisible(document->isMaskVisible()), m_transformation(document->getTransformation()) {
    auto editor = UIContext::instance()->activeEditor();
    m_layerId = editor->layer() ? editor->layer()->id() : 0;
    m_frame = editor->frame();
  }
  ~SelectionGuard() {
    if (committed) return;
    try {
      auto editor = UIContext::instance()->activeEditor();
      // Native SetMask undo intentionally forgets a hidden/deselected mask.
      // A FAILED operation must preserve even that retained manual state.
      m_document->setMask(m_mask.get());
      m_document->setMaskVisible(m_maskVisible);
      m_document->setTransformation(m_transformation);
      for (auto layer : m_document->sprite()->layers()) if (layer->id() == m_layerId) editor->setLayer(layer);
      editor->setFrame(std::min(m_frame, m_document->sprite()->lastFrame()));
      m_document->generateMaskBoundaries();
      m_document->notifyGeneralUpdate();
    } catch (...) { /* Preserve the original operation error. */ }
  }
  bool committed = false;
private:
  Document* m_document;
  ObjectId m_layerId;
  frame_t m_frame;
  std::unique_ptr<Mask> m_mask;
  bool m_maskVisible;
  Transformation m_transformation;
};
void nonblocking(int fd) {
  if (fcntl(fd, F_SETFL, O_NONBLOCK) < 0 || fcntl(fd, F_SETFD, FD_CLOEXEC) < 0)
    throw std::runtime_error("Cannot configure automation socket.");
#ifdef __APPLE__
  int enabled = 1;
  setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &enabled, sizeof(enabled));
#endif
}
bool sameUser(int fd) {
#ifdef __APPLE__
  uid_t uid; gid_t gid;
  return getpeereid(fd, &uid, &gid) == 0 && uid == getuid();
#else
  struct ucred peer;
  socklen_t length = sizeof(peer);
  return getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &length) == 0 && peer.uid == getuid();
#endif
}
void uiIdle() {
  auto manager = ui::Manager::getDefault();
  auto foreground = manager->getForegroundWindow();
  require(!manager->getCapture() && (!foreground || foreground == App::instance()->mainWindow()), "BUSY", "Finish the current GUI gesture or modal dialog first.");
  auto editor = UIContext::instance()->activeEditor();
  require(!editor || (!editor->isPlaying() && dynamic_cast<StandbyState*>(editor->getState().get())), "BUSY", "Finish drawing, playback, or transforming before accessing the bridge.");
}
Json summary(Document* document) {
  auto sprite = document->sprite();
  return {{"documentId", document->id()}, {"name", document->filename()},
          {"width", sprite->width()}, {"height", sprite->height()},
          {"frameCount", sprite->totalFrames()}, {"colorMode", sprite->pixelFormat() == IMAGE_RGB ? "rgba" : sprite->pixelFormat() == IMAGE_INDEXED ? "indexed" : "grayscale"},
          {"modified", document->isModified()}, {"hasFile", document->isAssociatedToFile()}, {"transparentIndex", sprite->pixelFormat() == IMAGE_INDEXED ? Json(sprite->transparentColor()) : Json(nullptr)}};
}
}

class AutomationBridge::Impl {
public:
  Impl(const std::string& path, const std::string& root) : m_path(path), m_timer(16) {
    require(!root.empty() && fs::is_directory(root), "INVALID_ROOT", "--automation-root must name an existing directory.");
    m_root = fs::canonical(root);
    require(fs::path(path).is_absolute(), "INVALID_SOCKET", "Socket path must be absolute.");
    struct stat parent;
    require(lstat(fs::path(path).parent_path().c_str(), &parent) == 0 && S_ISDIR(parent.st_mode) && parent.st_uid == getuid() && (parent.st_mode & 0077) == 0,
            "INVALID_SOCKET", "Socket parent must be a private directory owned by the current user (mode 0700).");
    struct sockaddr_un address = {};
    address.sun_family = AF_UNIX;
    require(path.size() < sizeof(address.sun_path), "INVALID_SOCKET", "Socket path is too long.");
    std::memcpy(address.sun_path, path.c_str(), path.size() + 1);
    // Never unlink a pre-existing endpoint: it may belong to another editor.
    require(!fs::exists(fs::symlink_status(path)), "SOCKET_EXISTS", "Socket already exists. Choose another endpoint or remove a confirmed stale socket.");
    m_listener = socket(AF_UNIX, SOCK_STREAM, 0);
    require(m_listener >= 0, "IO_ERROR", "Cannot create automation socket.");
    try {
      nonblocking(m_listener);
      require(bind(m_listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0, "IO_ERROR", "Cannot bind automation socket.");
      m_bound = true;
      require(chmod(path.c_str(), 0600) == 0 && listen(m_listener, 1) == 0, "IO_ERROR", "Cannot secure/listen on automation socket.");
      std::random_device random;
      std::ostringstream session;
      for (int i = 0; i < 4; ++i) session << std::hex << std::setw(8) << std::setfill('0') << random();
      m_session = session.str();
      // Only opt-in editor processes get this persistent control. Ordinary
      // status messages (brush, coordinates, etc.) cannot overwrite its state.
      m_control.reset(new ui::Button("AI: Waiting (paused)"));
      m_control->setId("automation-control");
      setup_mini_look(m_control.get());
      m_control->Click.connect([this] { toggleFromEditor(); });
      auto tooltip = new ui::TooltipManager;
      m_control->addChild(tooltip);
      tooltip->addTooltipFor(m_control.get(), "Pause agent requests before manual work. A local pause can only be released here.", ui::TOP);
      StatusBar::instance()->addChild(m_control.get());
      updateControl();
      m_timer.Tick.connect([this] { tick(); });
      m_timer.start();
    } catch (...) {
      removeControl();
      close(m_listener);
      if (m_bound) unlink(m_path.c_str());
      throw;
    }
  }
  ~Impl() {
    m_timer.stop();
    disconnect();
    removeControl();
    if (m_listener >= 0) close(m_listener);
    if (m_bound) unlink(m_path.c_str());
  }
private:
  struct Cached { std::string id, request, response; };
  struct Revision { std::string fingerprint; int number = 0; };
  std::string m_path, m_session, m_input, m_output;
  fs::path m_root;
  ui::Timer m_timer;
  int m_listener = -1, m_client = -1;
  bool m_bound = false, m_paused = true, m_pausedByUser = false;
  std::unique_ptr<ui::Button> m_control;
  size_t m_sent = 0, m_cacheBytes = 0;
  Clock::time_point m_progress = Clock::now();
  std::deque<Cached> m_cache;
  std::map<ObjectId, Revision> m_revisions;

  void updateControl() {
    if (!m_control) return;
    m_control->setText(m_client < 0 ? "AI: Waiting (paused)" : m_paused ? "AI: Paused | Resume" : "AI: Enabled | Pause");
    m_control->setEnabled(m_client >= 0);
    if (m_control->parent()) m_control->parent()->layout();
    m_control->invalidate();
  }
  void removeControl() {
    if (!m_control) return;
    auto parent = m_control->parent();
    if (parent) parent->removeChild(m_control.get());
    m_control.reset();
    if (parent) parent->layout();
  }
  void toggleFromEditor() {
    if (m_client < 0) return;
    if (!m_paused) {
      // Pausing never waits for an idle editor. Native operations are UI-thread
      // synchronous: this stops the NEXT request, not an operation in progress.
      m_paused = true;
      m_pausedByUser = true;
    } else {
      try { uiIdle(); }
      catch (const std::exception& error) {
        StatusBar::instance()->setStatusText(3000, "%s", error.what());
        return;
      }
      m_pausedByUser = false;
      m_paused = false;
    }
    updateControl();
  }
  void disconnect() {
    if (m_client >= 0) close(m_client);
    m_client = -1;
    m_input.clear(); m_output.clear(); m_sent = 0;
    // Disconnect is a safety boundary: edits require explicit resume.
    m_paused = true;
    updateControl();
  }
  void tick() noexcept {
    try {
      if (m_client < 0) {
        int fd = accept(m_listener, nullptr, nullptr);
        if (fd < 0) return;
        if (!sameUser(fd)) { close(fd); return; }
        try { nonblocking(fd); } catch (...) { close(fd); throw; }
        m_client = fd; m_progress = Clock::now();
        updateControl();
      }
      if ((!m_input.empty() || !m_output.empty()) && Clock::now() - m_progress > std::chrono::seconds(5)) { disconnect(); return; }
      if (!m_output.empty()) {
        size_t amount = std::min(size_t(256 * 1024), m_output.size() - m_sent);
#ifdef __linux__
        auto count = send(m_client, m_output.data() + m_sent, amount, MSG_NOSIGNAL);
#else
        auto count = send(m_client, m_output.data() + m_sent, amount, 0);
#endif
        if (count > 0) {
          m_sent += size_t(count); m_progress = Clock::now();
          if (m_sent == m_output.size()) { m_output.clear(); m_sent = 0; }
        } else if (count < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) disconnect();
        return;
      }
      char buffer[16384];
      for (int i = 0; i < 16 && m_input.find('\n') == std::string::npos; ++i) {
        auto count = recv(m_client, buffer, sizeof(buffer), 0);
        if (count > 0) { m_input.append(buffer, size_t(count)); m_progress = Clock::now(); }
        else if (count == 0) { disconnect(); return; }
        else { if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) disconnect(); break; }
      }
      if (m_input.size() > MaxRequest) { disconnect(); return; }
      auto end = m_input.find('\n');
      if (end == std::string::npos) return;
      std::string line = m_input.substr(0, end);
      m_input.erase(0, end + 1);
      m_output = handle(line) + "\n"; m_sent = 0;
    } catch (...) { disconnect(); }
  }

  Json details(Document* document) {
    auto result = summary(document);
    auto sprite = document->sprite();
    require(sprite->width() <= 1024 && sprite->height() <= 1024 && sprite->totalFrames() <= 256,
            "LIMIT_EXCEEDED", "The bridge supports at most 1024x1024 canvas pixels and 256 frames.");
    result["layers"] = Json::array();
    int count = 0;
    for (auto layer : sprite->layers()) {
      require(++count <= 128, "LIMIT_EXCEEDED", "This first bridge supports at most 128 layers.");
      Json item = {{"layerId", layer->id()}, {"name", layer->name()}, {"visible", layer->isVisible()},
                   {"editable", layer->isEditable()}, {"background", layer->isBackground()},
                   {"parentId", layer->parent() == sprite->folder() ? Json(nullptr) : Json(layer->parent()->id())},
                    {"type", layer->isImage() ? "image" : "group"}, {"version", layer->version()}};
      item["continuous"] = layer->isContinuous(); item["movable"] = layer->isMovable();
      if (!layer->userData().isEmpty()) item["userData"] = {{"text", layer->userData().text()}, {"color", layer->userData().color()}};
      if (layer->isImage()) {
        auto imageLayer = static_cast<LayerImage*>(layer);
        item["opacity"] = imageLayer->opacity(); item["blendMode"] = int(imageLayer->blendMode());
        item["cels"] = Json::array();
        for (auto it = imageLayer->getCelBegin(); it != imageLayer->getCelEnd(); ++it) {
          auto cel = *it;
          Json celInfo = {{"celId", cel->id()}, {"celDataId", cel->data()->id()}, {"frame", cel->frame()}, {"x", cel->x()}, {"y", cel->y()}, {"opacity", cel->opacity()},
                                  {"width", cel->image()->width()}, {"height", cel->image()->height()},
                                  {"imageId", cel->image()->id()}, {"imageVersion", cel->image()->version()}, {"links", cel->links()}};
          if (!cel->data()->userData().isEmpty()) celInfo["userData"] = {{"text", cel->data()->userData().text()}, {"color", cel->data()->userData().color()}};
          item["cels"].push_back(std::move(celInfo));
        }
      }
      result["layers"].push_back(item);
    }
    result["frames"] = Json::array();
    for (frame_t frame = 0; frame < sprite->totalFrames(); ++frame)
      result["frames"].push_back({{"frame", frame}, {"durationMs", sprite->frameDuration(frame)}});
    result["palettes"] = Json::array();
    require(sprite->getPalettes().size() <= 256, "LIMIT_EXCEEDED", "At most 256 palette keyframes are supported.");
    for (const auto& palette : sprite->getPalettes()) {
      require(palette->size() <= 4096, "LIMIT_EXCEEDED", "Palette is too large.");
      Json entries = Json::array();
      for (int i = 0; i < palette->size(); ++i) entries.push_back(palette->getEntry(i));
      result["palettes"].push_back({{"frame", palette->frame()}, {"rgbaPacked", entries}});
    }
    result["tags"] = Json::array();
    require(sprite->frameTags().size() <= 128, "LIMIT_EXCEEDED", "At most 128 animation tags are supported.");
    for (auto tag : sprite->frameTags())
      result["tags"].push_back({{"tagId", tag->id()}, {"name", tag->name()}, {"from", tag->fromFrame()}, {"to", tag->toFrame()}, {"direction", int(tag->aniDir())}, {"color", tag->color()}});
    result["canUndo"] = document->undoHistory()->canUndo();
    result["canRedo"] = document->undoHistory()->canRedo();
    result["selection"] = selectionInfo(document);
    return result;
  }
  Json selectionInfo(Document* document) {
    auto mask = document->mask();
    auto bounds = mask->bounds();
    size_t selected = 0;
    if (auto bitmap = mask->bitmap()) {
      require(size_t(bitmap->width()) * bitmap->height() <= MaxPixels, "LIMIT_EXCEEDED", "Selection exceeds 1,048,576 bitmap pixels.");
      for (int y = 0; y < bitmap->height(); ++y)
        for (int x = 0; x < bitmap->width(); ++x) selected += bitmap->getPixel(x, y) != 0;
    }
    return {{"visible", document->isMaskVisible()}, {"x", bounds.x}, {"y", bounds.y},
            {"width", bounds.w}, {"height", bounds.h}, {"selectedPixels", selected}};
  }
  int revision(Document* document, const Json& metadata) {
    // Fingerprint native state AND image bytes: catches ordinary manual edits,
    // undo/redo, palette changes, and script writes that bypass undo commands.
    SHA1Context hash; SHA1Reset(&hash);
    // Upstream crash::Writer::saveObject initializes zero versions to one in
    // its background recovery pass, even for unchanged layers/images. Treat
    // ONLY that initial bookkeeping transition as equivalent. Higher counters,
    // actual properties/pixel bytes, IDs, and undo state still detect edits.
    auto fingerprintMetadata = automation::revisionMetadata(metadata);
    std::string encoded = fingerprintMetadata.dump() + std::to_string(reinterpret_cast<uintptr_t>(document->undoHistory()->currentState()));
    SHA1Input(&hash, reinterpret_cast<const uint8_t*>(encoded.data()), unsigned(encoded.size()));
    std::vector<Image*> images;
    document->sprite()->getImages(images);
    size_t total = 0;
    for (auto image : images) {
      size_t size = size_t(image->getRowStrideSize()) * size_t(image->height());
      total += size;
      require(total <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Sprite image data exceeds the bridge's 32 MiB working limit.");
      SHA1Input(&hash, image->getPixelAddress(0, 0), unsigned(size));
    }
    // Selection is document state too: manual masks can have the same bounding
    // box/pixel count while selecting different pixels. Hash actual bitmap bits.
    if (auto bitmap = document->mask()->bitmap()) {
      size_t size = size_t(bitmap->getRowStrideSize()) * bitmap->height();
      SHA1Input(&hash, bitmap->getPixelAddress(0, 0), unsigned(size));
    }
    uint8_t digest[SHA1HashSize]; SHA1Result(&hash, digest);
    std::string fingerprint(reinterpret_cast<char*>(digest), sizeof(digest));
    auto& record = m_revisions[document->id()];
    if (record.fingerprint != fingerprint) { record.fingerprint = fingerprint; ++record.number; }
    return record.number;
  }
  Json inspect(Document* document) {
    auto result = details(document);
    result["revision"] = revision(document, result);
    result["sessionId"] = m_session;
    auto editor = UIContext::instance()->activeEditor();
    bool active = editor && editor->document() == document;
    result["activeLayerId"] = active && editor->layer() ? Json(editor->layer()->id()) : Json(nullptr);
    result["activeFrame"] = active ? Json(editor->frame()) : Json(nullptr);
    return result;
  }
  Document* findDocument(const Json& params) {
    auto id = integer(params, "documentId", 1, INT32_MAX);
    auto document = dynamic_cast<Document*>(UIContext::instance()->documents().getById(id));
    require(document, "DOCUMENT_NOT_FOUND", "Document no longer exists in this editor.");
    return document;
  }
  void checkRevision(Document* document, const Json& params) {
    int expected = integer(params, "expectedRevision", 1, INT32_MAX);
    require(inspect(document)["revision"] == expected, "STALE_REVISION", "Document changed. Inspect it again before editing.");
  }
  void documentViewsIdle(Document* document) {
    for (auto view : UIContext::instance()->getAllDocumentViews(document)) {
      auto editor = view->editor();
      require(!editor->isPlaying() && dynamic_cast<StandbyState*>(editor->getState().get()), "BUSY", "Finish playback/drawing/transforming in every view of the target document first.");
    }
  }
  Json activateDocument(Document* document, const Json& params) {
    auto ctx = UIContext::instance();
    require(params.contains("expectedActiveDocumentId"), "INVALID_PARAMS", "Supply expectedActiveDocumentId (null when no sprite is active).");
    auto active = ctx->activeDocument();
    const auto& expected = params["expectedActiveDocumentId"];
    if (expected.is_null()) require(!active, "ACTIVE_DOCUMENT_CHANGED", "The active document changed. List documents again before switching.");
    else {
      int id = integer(params, "expectedActiveDocumentId", 1, INT32_MAX);
      require(active && active->id() == ObjectId(id), "ACTIVE_DOCUMENT_CHANGED", "The active document changed. List documents again before switching.");
    }
    DocumentReader reader(document, 0);
    checkRevision(document, params);
    documentViewsIdle(document);
    auto view = ctx->getFirstDocumentView(document);
    require(view, "VIEW_NOT_FOUND", "Target document has no editable GUI view.");
    // Preserve the current cloned view when this document is already active.
    if (active != document) ctx->setActiveView(view);
    return inspect(document);
  }
  Json focusSite(Document* document, const Json& params) {
    DocumentReader reader(document, 0);
    checkRevision(document, params);
    require(params.contains("layerId") || params.contains("frame"), "INVALID_PARAMS", "Supply layerId and/or frame.");
    auto editor = UIContext::instance()->activeEditor();
    auto layer = params.contains("layerId") ? findLayer(document->sprite(), integer(params, "layerId", 1, INT32_MAX)) : editor->layer();
    int frame = params.contains("frame") ? integer(params, "frame", 0, document->sprite()->lastFrame()) : editor->frame();
    // Validate both BEFORE changing either. Locked/hidden/group layers can be
    // focused for review; this neither paints nor changes their properties.
    if (editor->layer() != layer) editor->setLayer(layer);
    editor->setFrame(frame);
    editor->requestFocus();
    set_current_palette(document->sprite()->palette(frame), false);
    update_screen_for_document(document);
    return inspect(document);
  }
  Json closeDocument(Document* document, const Json& params) {
    require(boolean(params, "confirm"), "INVALID_PARAMS", "Closing a document requires confirm: true.");
    auto ctx = UIContext::instance();
    DocumentDestroyer destroyer(ctx, document, 0);
    checkRevision(document, params);
    require(document->isAssociatedToFile() && !document->isModified(), "UNSAVED_CHANGES", "Save this sprite to a native file before closing. Discarding unsaved work is not supported.");
    documentViewsIdle(document);
    auto id = document->id();
    int lastRevision = inspect(document)["revision"];
    // Use native document destruction, not CloseFile's interactive Save/Discard
    // dialog. This closes all views and releases undo history without quitting.
    destroyer.destroyDocument();
    m_revisions.erase(id);
    App::instance()->updateDisplayTitleBar();
    return {{"closedDocumentId", id}, {"lastRevision", lastRevision}, {"activeDocumentId", ctx->activeDocument() ? Json(ctx->activeDocument()->id()) : Json(nullptr)}, {"sessionId", m_session}};
  }
  fs::path filePath(const Json& params, bool saving) {
    fs::path input(text(params, "path"));
    require(!input.is_absolute(), "PATH_OUTSIDE_ROOT", "Use a path relative to the configured asset root.");
    auto candidate = m_root / input;
    auto parent = fs::canonical(candidate.parent_path());
    auto resolved = saving ? parent / candidate.filename() : fs::canonical(candidate);
    auto relative = resolved.lexically_relative(m_root);
    require(!relative.empty() && *relative.begin() != "..", "PATH_OUTSIDE_ROOT", "Path escapes the configured asset root.");
    if (saving) require(!fs::is_symlink(fs::symlink_status(candidate)), "INVALID_PATH", "Refusing to save through a symlink.");
    return resolved;
  }
  bool supportedAsset(const fs::path& path) {
    return path.extension() == ".png" || path.extension() == ".ase" || path.extension() == ".aseprite";
  }
  std::unique_ptr<Document> loadAsset(const fs::path& path) {
    require(fs::is_regular_file(path) && fs::file_size(path) <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Open requires a regular file of at most 32 MiB.");
    require(supportedAsset(path), "UNSUPPORTED_FORMAT", "Opening currently supports native sprites and PNG.");
    std::unique_ptr<FileOp> operation(FileOp::createLoadDocumentOperation(nullptr, path.c_str(), FILE_LOAD_SEQUENCE_NONE));
    require(operation && !operation->hasError(), "OPEN_FAILED", operation ? operation->error() : "Cannot create native load operation.");
    operation->operate(); operation->done();
    require(!operation->hasError() && operation->document(), "OPEN_FAILED", operation->hasError() ? operation->error() : "File did not produce a document.");
    // Validate before postLoad's optional palette generation. Codecs themselves
    // still aren't a sandbox: compressed input may allocate before these checks.
    details(operation->document()); workingLimits(operation->document());
    operation->postLoad();
    require(!operation->hasError() && operation->document(), "OPEN_FAILED", operation->hasError() ? operation->error() : "File did not produce a document.");
    return std::unique_ptr<Document>(operation->releaseDocument());
  }
  Json listAssets(const Json& params) {
    auto directory = filePath({{"path", params.contains("path") ? text(params, "path") : "."}}, false);
    require(fs::is_directory(directory), "INVALID_PATH", "Asset listing requires a directory inside the root.");
    int offset = params.contains("offset") ? integer(params, "offset", 0, 4096) : 0;
    int limit = params.contains("limit") ? integer(params, "limit", 1, 100) : 50;
    std::vector<Json> entries;
    int scanned = 0;
    for (const auto& entry : fs::directory_iterator(directory)) {
      require(++scanned <= 4096, "LIMIT_EXCEEDED", "Directory has more than 4096 entries. Browse a smaller subdirectory.");
      auto status = entry.symlink_status();
      // Browsing never follows links (including in-root links) or special files.
      if (fs::is_symlink(status)) continue;
      bool folder = fs::is_directory(status);
      if (!folder && !(fs::is_regular_file(status) && supportedAsset(entry.path()))) continue;
      Json item = {{"path", entry.path().lexically_relative(m_root).generic_string()}, {"name", entry.path().filename().string()}, {"type", folder ? "directory" : "asset"}};
      if (!folder) { item["bytes"] = entry.file_size(); item["format"] = entry.path().extension().string().substr(1); }
      entries.push_back(item);
    }
    std::sort(entries.begin(), entries.end(), [](const Json& a, const Json& b) {
      if (a["type"] != b["type"]) return a["type"] == "directory";
      return a["name"].get<std::string>() < b["name"].get<std::string>();
    });
    require(size_t(offset) <= entries.size(), "INVALID_PARAMS", "offset exceeds this directory's current entry count. List again from zero.");
    Json page = Json::array();
    size_t end = std::min(entries.size(), size_t(offset + limit));
    for (size_t i = size_t(offset); i < end; ++i) page.push_back(entries[i]);
    return {{"path", directory.lexically_relative(m_root).generic_string()}, {"entries", page}, {"total", entries.size()}, {"nextOffset", end < entries.size() ? Json(end) : Json(nullptr)}, {"sessionId", m_session}};
  }
  ImageRef composite(Sprite* sprite, frame_t frame, const render::OnionskinOptions* onions = nullptr) {
    ImageRef image(Image::create(IMAGE_RGB, sprite->width(), sprite->height()));
    image->clear(0);
    render::Render renderer;
    renderer.setBgType(render::BgType::TRANSPARENT);
    if (onions) renderer.setOnionskin(*onions);
    renderer.renderSprite(image.get(), sprite, frame);
    return image;
  }
  std::vector<uint8_t> encodePng(const Image* image, int scale = 1) {
    require(size_t(image->width()) * size_t(image->height()) * scale * scale <= MaxPixels,
            "LIMIT_EXCEEDED", "Image exceeds 1,048,576 output pixels. Reduce frames, columns, padding, or scale.");
    std::shared_ptr<she::Surface> surface(she::instance()->createRgbaSurface(image->width() * scale, image->height() * scale), [](she::Surface* surface) { surface->dispose(); });
    require(bool(surface), "RENDER_FAILED", "Cannot allocate preview surface.");
    for (int y = 0; y < surface->height(); ++y)
      for (int x = 0; x < surface->width(); ++x) surface->putPixel(image->getPixel(x / scale, y / scale), x, y);
    auto bytes = she::instance()->encodeSurfaceAsPNG(surface.get());
    require(!bytes.empty(), "RENDER_FAILED", "Cannot encode PNG image.");
    return bytes;
  }
  void addPng(Json& result, const std::vector<uint8_t>& bytes) {
    std::string encoded;
    base::encode_base64(bytes, encoded);
    result["pngBase64"] = encoded;
  }
  Json previewMetadata(Document* document) {
    auto result = summary(document);
    result["revision"] = revision(document, details(document));
    result["sessionId"] = m_session;
    return result;
  }
  Json previewAsset(const Json& params) {
    auto path = filePath(params, false);
    auto document = loadAsset(path);
    auto sprite = document->sprite();
    int frame = params.contains("frame") ? integer(params, "frame", 0, sprite->totalFrames() - 1) : 0;
    int scale = params.contains("scale") ? integer(params, "scale", 1, 16) : 1;
    require(size_t(sprite->width()) * sprite->height() * scale * scale <= MaxPixels, "LIMIT_EXCEEDED", "Preview exceeds 1,048,576 output pixels. Use a smaller scale.");
    auto result = summary(document.get());
    result.erase("documentId"); result.erase("name"); result.erase("modified");
    result["path"] = path.lexically_relative(m_root).generic_string();
    result["frame"] = frame; result["scale"] = scale;
    result["outputWidth"] = sprite->width() * scale; result["outputHeight"] = sprite->height() * scale;
    result["durationMs"] = sprite->frameDuration(frame); result["sessionId"] = m_session;
    // No setContext(), inspect(), selection changes, or persistent document IDs.
    addPng(result, encodePng(composite(sprite, frame).get(), scale));
    return result;
  }
  Json renderFrame(Document* document, const Json& params) {
    auto sprite = document->sprite();
    auto frame = integer(params, "frame", 0, sprite->totalFrames() - 1);
    auto scale = integer(params, "scale", 1, 16);
    require(size_t(sprite->width()) * sprite->height() * scale * scale <= MaxPixels, "LIMIT_EXCEEDED", "Preview exceeds 1,048,576 output pixels. Use a smaller scale.");
    auto result = inspect(document);
    addPng(result, encodePng(composite(sprite, frame).get(), scale));
    result["frame"] = frame; result["scale"] = scale;
    return result;
  }
  Json renderOnionSkin(Document* document, const Json& params) {
    auto sprite = document->sprite();
    int frame = integer(params, "frame", 0, sprite->totalFrames() - 1);
    int scale = params.contains("scale") ? integer(params, "scale", 1, 16) : 1;
    require(size_t(sprite->width()) * sprite->height() * scale * scale <= MaxPixels, "LIMIT_EXCEEDED", "Preview exceeds 1,048,576 output pixels. Use a smaller scale.");
    auto mode = params.contains("mode") ? text(params, "mode", 16) : "tint";
    auto position = params.contains("position") ? text(params, "position", 16) : "behind";
    require(mode == "tint" || mode == "merge", "INVALID_PARAMS", "mode must be tint or merge.");
    require(position == "behind" || position == "front", "INVALID_PARAMS", "position must be behind or front.");
    render::OnionskinOptions onions(mode == "tint" ? render::OnionskinType::RED_BLUE_TINT : render::OnionskinType::MERGE);
    onions.position(position == "behind" ? render::OnionskinPosition::BEHIND : render::OnionskinPosition::INFRONT);
    onions.prevFrames(params.contains("previous") ? integer(params, "previous", 0, 8) : 1);
    onions.nextFrames(params.contains("next") ? integer(params, "next", 0, 8) : 1);
    onions.opacityBase(params.contains("opacity") ? integer(params, "opacity", 0, 255) : 128);
    onions.opacityStep(params.contains("opacityStep") ? integer(params, "opacityStep", 0, 255) : 32);
    if (params.contains("layerId")) onions.layer(findLayer(sprite, integer(params, "layerId", 1, INT32_MAX)));
    auto result = previewMetadata(document);
    result["frame"] = frame; result["scale"] = scale; result["mode"] = mode; result["position"] = position;
    result["previous"] = onions.prevFrames(); result["next"] = onions.nextFrames();
    result["opacity"] = onions.opacityBase(); result["opacityStep"] = onions.opacityStep();
    result["layerId"] = onions.layer() ? Json(onions.layer()->id()) : Json(nullptr);
    result["outputWidth"] = sprite->width() * scale; result["outputHeight"] = sprite->height() * scale;
    addPng(result, encodePng(composite(sprite, frame, &onions).get(), scale));
    return result;
  }
  struct Sheet { ImageRef image; Json manifest; };
  Sheet spriteSheet(Document* document, const Json& params) {
    auto sprite = document->sprite();
    std::vector<int> frames;
    if (params.contains("frames")) {
      require(params["frames"].is_array() && !params["frames"].empty() && params["frames"].size() <= 256, "INVALID_PARAMS", "Provide 1 to 256 unique frame indices, or omit frames for all.");
      for (const auto& value : params["frames"]) {
        int frame = integer({{"frame", value}}, "frame", 0, sprite->totalFrames() - 1);
        require(std::find(frames.begin(), frames.end(), frame) == frames.end(), "INVALID_PARAMS", "Repeated frame indices are not supported.");
        frames.push_back(frame);
      }
    } else for (int frame = 0; frame < sprite->totalFrames(); ++frame) frames.push_back(frame);
    int scale = params.contains("scale") ? integer(params, "scale", 1, 16) : 1;
    int columns = params.contains("columns") ? integer(params, "columns", 1, 16) : std::min(16, int(std::ceil(std::sqrt(frames.size()))));
    require(size_t(columns) <= frames.size(), "INVALID_PARAMS", "columns cannot exceed the number of selected frames.");
    int padding = params.contains("padding") ? integer(params, "padding", 0, 16) : 0;
    int rows = (int(frames.size()) + columns - 1) / columns;
    int cellWidth = sprite->width() * scale, cellHeight = sprite->height() * scale;
    int width = columns * cellWidth + (columns + 1) * padding;
    int height = rows * cellHeight + (rows + 1) * padding;
    require(uint64_t(width) * uint64_t(height) <= MaxPixels, "LIMIT_EXCEEDED", "Sheet exceeds 1,048,576 output pixels. Reduce frames, padding, or scale.");
    Sheet result{ImageRef(Image::create(IMAGE_RGB, width, height)), {{"schema", "libresprite-sheet-v1"}, {"width", width}, {"height", height}, {"columns", columns}, {"rows", rows}, {"padding", padding}, {"scale", scale}, {"sourceWidth", sprite->width()}, {"sourceHeight", sprite->height()}, {"frames", Json::array()}, {"tags", Json::array()}}};
    result.image->clear(0);
    for (size_t i = 0; i < frames.size(); ++i) {
      int x = padding + int(i % columns) * (cellWidth + padding), y = padding + int(i / columns) * (cellHeight + padding);
      auto image = composite(sprite, frames[i]);
      for (int dy = 0; dy < cellHeight; ++dy)
        for (int dx = 0; dx < cellWidth; ++dx) result.image->putPixel(x + dx, y + dy, image->getPixel(dx / scale, dy / scale));
      result.manifest["frames"].push_back({{"frame", frames[i]}, {"x", x}, {"y", y}, {"width", cellWidth}, {"height", cellHeight}, {"durationMs", sprite->frameDuration(frames[i])}});
    }
    // Tag ranges refer to SOURCE frame indices, even for reordered/subset sheets.
    for (auto tag : sprite->frameTags())
      result.manifest["tags"].push_back({{"name", tag->name()}, {"from", tag->fromFrame()}, {"to", tag->toFrame()}, {"direction", int(tag->aniDir())}});
    return result;
  }
  Json contactSheet(Document* document, const Json& params) {
    auto result = previewMetadata(document);
    auto sheet = spriteSheet(document, params);
    result["sheet"] = sheet.manifest;
    addPng(result, encodePng(sheet.image.get()));
    return result;
  }
  void publishExport(const fs::path& path, const std::vector<uint8_t>& bytes, bool overwrite) {
    auto status = fs::symlink_status(path);
    require(!fs::is_symlink(status) && !fs::is_directory(status), "INVALID_PATH", "Refusing to export over a symlink or directory.");
    require(overwrite || !fs::exists(status), "FILE_EXISTS", "Destination exists; explicitly allow overwrite or choose another filename.");
    std::string pattern = (path.parent_path() / ".libresprite-export-XXXXXX").string();
    std::vector<char> temporary(pattern.begin(), pattern.end()); temporary.push_back('\0');
    int fd = mkstemp(temporary.data());
    require(fd >= 0, "IO_ERROR", "Cannot create temporary export file.");
    try {
      size_t written = 0;
      while (written < bytes.size()) {
        auto count = write(fd, bytes.data() + written, bytes.size() - written);
        if (count < 0 && errno == EINTR) continue;
        require(count > 0, "IO_ERROR", "Cannot write export.");
        written += size_t(count);
      }
      int closeResult = close(fd); fd = -1;
      require(closeResult == 0, "IO_ERROR", "Cannot finish export.");
      if (overwrite) fs::rename(temporary.data(), path);
      else {
        auto published = link(temporary.data(), path.c_str());
        require(published == 0, errno == EEXIST ? "FILE_EXISTS" : "IO_ERROR", "Could not publish export; destination may have appeared during export.");
        unlink(temporary.data());
      }
    } catch (...) { if (fd >= 0) close(fd); unlink(temporary.data()); throw; }
  }
  Json exportPng(Document* document, const Json& params, bool sheet) {
    auto path = filePath(params, true);
    require(path.extension() == ".png", "INVALID_PATH", "PNG export requires a .png path.");
    bool overwrite = params.contains("overwrite") ? boolean(params, "overwrite") : false;
    auto result = previewMetadata(document);
    std::vector<uint8_t> bytes;
    if (sheet) {
      auto rendered = spriteSheet(document, params);
      result["sheet"] = rendered.manifest;
      bytes = encodePng(rendered.image.get());
    } else {
      int frame = integer(params, "frame", 0, document->sprite()->totalFrames() - 1);
      int scale = params.contains("scale") ? integer(params, "scale", 1, 16) : 1;
      require(size_t(document->sprite()->width()) * document->sprite()->height() * scale * scale <= MaxPixels, "LIMIT_EXCEEDED", "Export exceeds 1,048,576 output pixels. Use a smaller scale.");
      result["frame"] = frame; result["scale"] = scale;
      result["outputWidth"] = document->sprite()->width() * scale; result["outputHeight"] = document->sprite()->height() * scale;
      bytes = encodePng(composite(document->sprite(), frame).get(), scale);
    }
    result["path"] = path.lexically_relative(m_root).generic_string(); result["bytes"] = bytes.size();
    // Prepare/check the entire result before any file-system side effect.
    require(result.dump().size() < MaxResponse - 4096, "LIMIT_EXCEEDED", "Export metadata exceeds the bridge limit.");
    publishExport(path, bytes, overwrite);
    return result;
  }
  FrameTag* findTag(Sprite* sprite, const Json& params) {
    auto tag = sprite->frameTags().getById(integer(params, "tagId", 1, INT32_MAX));
    require(tag, "TAG_NOT_FOUND", "Tag no longer exists in this document.");
    return tag;
  }
  AniDir tagDirection(const Json& params) {
    auto value = text(params, "direction", 16);
    require(value == "forward" || value == "reverse" || value == "pingpong", "INVALID_PARAMS", "direction must be forward, reverse, or pingpong.");
    return value == "forward" ? AniDir::FORWARD : value == "reverse" ? AniDir::REVERSE : AniDir::PING_PONG;
  }
  Json editTags(Document* document, const Json& params, const std::string& method) {
    auto sprite = document->sprite();
    if (method == "remove_tag") {
      auto tag = findTag(sprite, params);
      Transaction transaction(UIContext::instance(), "AI remove tag");
      transaction.execute(new cmd::RemoveFrameTag(sprite, tag));
      finish(transaction, document);
      return Json::object();
    }
    bool creating = method == "create_tag";
    auto tag = creating ? nullptr : findTag(sprite, params);
    if (creating) require(sprite->frameTags().size() < 128, "LIMIT_EXCEEDED", "At most 128 tags are supported.");
    else require(params.contains("name") || params.contains("from") || params.contains("to") || params.contains("direction") || params.contains("color"), "INVALID_PARAMS", "Provide at least one tag property.");
    auto name = creating || params.contains("name") ? text(params, "name", 120) : tag->name();
    int from = creating || params.contains("from") ? integer(params, "from", 0, sprite->lastFrame()) : tag->fromFrame();
    int to = creating || params.contains("to") ? integer(params, "to", 0, sprite->lastFrame()) : tag->toFrame();
    require(from <= to, "INVALID_PARAMS", "Tag from must not exceed to.");
    auto direction = params.contains("direction") ? tagDirection(params) : creating ? AniDir::FORWARD : tag->aniDir();
    auto tint = params.contains("color") ? color(params) : creating ? rgba(0, 0, 0, 255) : tag->color();
    require(rgba_geta(tint) == 255, "INVALID_PARAMS", "Tag label colors must be opaque (a=255).");
    if (creating) {
      std::unique_ptr<FrameTag> created(new FrameTag(from, to));
      created->setName(name); created->setAniDir(direction); created->setColor(tint);
      auto id = created->id();
      Transaction transaction(UIContext::instance(), "AI create tag");
      transaction.execute(new cmd::AddFrameTag(sprite, created.get())); created.release();
      finish(transaction, document);
      return {{"createdTagId", id}};
    }
    if (tag->name() != name || tag->fromFrame() != from || tag->toFrame() != to || tag->aniDir() != direction || tag->color() != tint) {
      Transaction transaction(UIContext::instance(), "AI tag properties");
      if (tag->name() != name) transaction.execute(new cmd::SetFrameTagName(tag, name));
      if (tag->fromFrame() != from || tag->toFrame() != to) transaction.execute(new cmd::SetFrameTagRange(tag, from, to));
      if (tag->aniDir() != direction) transaction.execute(new cmd::SetFrameTagAniDir(tag, direction));
      if (tag->color() != tint) transaction.execute(new cmd::SetFrameTagColor(tag, tint));
      finish(transaction, document);
    }
    return Json::object();
  }
  void validateIndexedPalette(Sprite* sprite, int frame, int size) {
    if (sprite->pixelFormat() != IMAGE_INDEXED) return;
    require(sprite->transparentColor() < size, "PALETTE_INDEX_IN_USE", "New palette size excludes the transparent index. No automatic index remapping is performed.");
    int end = sprite->totalFrames();
    for (auto palette : sprite->getPalettes()) if (palette->frame() > frame) { end = palette->frame(); break; }
    for (auto cel : sprite->cels()) {
      if (cel->frame() < frame || cel->frame() >= end) continue;
      auto image = cel->image();
      for (int y = 0; y < image->height(); ++y)
        for (int x = 0; x < image->width(); ++x)
          require(image->getPixel(x, y) < color_t(size), "PALETTE_INDEX_IN_USE", "New palette size excludes a cel's pixel index (including hidden/off-canvas pixels). No automatic remapping is performed.");
    }
  }
  void editPalette(Document* document, const Json& params, bool removing) {
    auto sprite = document->sprite();
    require(sprite->pixelFormat() != IMAGE_GRAYSCALE, "UNSUPPORTED_COLOR_MODE", "Grayscale sprites use a fixed grayscale ramp.");
    int frame = integer(params, "frame", 0, sprite->lastFrame());
    auto palette = sprite->palette(frame);
    if (removing) {
      require(frame > 0, "BASE_PALETTE", "The frame-zero palette cannot be removed.");
      require(palette->frame() == frame, "PALETTE_NOT_FOUND", "No palette keyframe exists at this frame.");
      validateIndexedPalette(sprite, frame, sprite->palette(frame - 1)->size());
      Transaction transaction(UIContext::instance(), "AI remove palette keyframe");
      transaction.execute(new cmd::RemovePalette(sprite, *palette));
      finish(transaction, document);
      return;
    }
    require(palette->size() <= 256, "UNSUPPORTED_PALETTE", "Palette editing currently supports palettes of at most 256 colors.");
    require(params.contains("size") || params.contains("entries"), "INVALID_PARAMS", "Provide entries and/or size.");
    int size = params.contains("size") ? integer(params, "size", 1, 256) : palette->size();
    auto changed = palette->clone(); changed->resize(size); changed->setFrame(frame);
    if (params.contains("entries")) {
      require(params["entries"].is_array() && !params["entries"].empty() && params["entries"].size() <= 256, "INVALID_PARAMS", "Provide 1 to 256 unique palette entries.");
      std::vector<int> indices;
      for (auto entry : params["entries"]) {
        int index = integer(entry, "index", 0, size - 1);
        require(std::find(indices.begin(), indices.end(), index) == indices.end(), "INVALID_PARAMS", "Palette entry indices must be unique.");
        indices.push_back(index); changed->setEntry(index, color(entry));
      }
    }
    if (*palette == *changed) return;
    validateIndexedPalette(sprite, frame, size);
    Transaction transaction(UIContext::instance(), "AI palette keyframe");
    // SetPalette edits the EFFECTIVE palette, so only use it at an exact key.
    if (palette->frame() == frame) transaction.execute(new cmd::SetPalette(sprite, frame, *changed));
    else transaction.execute(new cmd::AddPalette(sprite, *changed));
    finish(transaction, document);
  }
  std::vector<int> animationFrames(Sprite* sprite, const Json& params) {
    require(!(params.contains("tagId") && params.contains("frames")), "INVALID_PARAMS", "Choose either tagId or frames, not both.");
    std::vector<int> frames;
    if (params.contains("tagId")) {
      auto tag = findTag(sprite, params);
      require(tag->fromFrame() >= 0 && tag->toFrame() <= sprite->lastFrame() && tag->fromFrame() <= tag->toFrame(), "INVALID_PARAMS", "Tag range is outside this sprite.");
      require(int(tag->aniDir()) >= 0 && int(tag->aniDir()) <= 2, "INVALID_PARAMS", "Unsupported tag direction.");
      for (int frame = tag->fromFrame(); frame <= tag->toFrame(); ++frame) frames.push_back(frame);
      if (tag->aniDir() == AniDir::REVERSE) std::reverse(frames.begin(), frames.end());
      else if (tag->aniDir() == AniDir::PING_PONG)
        for (int frame = tag->toFrame() - 1; frame > tag->fromFrame(); --frame) frames.push_back(frame);
    } else if (params.contains("frames")) {
      require(params["frames"].is_array() && !params["frames"].empty() && params["frames"].size() <= 256, "INVALID_PARAMS", "Provide 1 to 256 animation frame indices, or omit for all.");
      for (auto frame : params["frames"]) frames.push_back(integer({{"frame", frame}}, "frame", 0, sprite->lastFrame()));
    } else for (int frame = 0; frame < sprite->totalFrames(); ++frame) frames.push_back(frame);
    return frames;
  }
  std::vector<uint8_t> encodeGif(Sprite* sprite, bool loop) {
    std::unique_ptr<Document> detached(new Document(sprite));
    detached->setFormatOptions(base::SharedPtr<FormatOptions>(new GifOptions(false, loop)));
    std::string pattern = (m_root / ".libresprite-gif-XXXXXX.gif").string();
    std::vector<char> temporary(pattern.begin(), pattern.end()); temporary.push_back('\0');
    int fd = mkstemps(temporary.data(), 4);
    require(fd >= 0, "IO_ERROR", "Cannot create native GIF encoding file."); close(fd);
    try {
      std::unique_ptr<FileOp> operation(FileOp::createSaveDocumentOperation(nullptr, detached.get(), temporary.data(), ""));
      require(operation && !operation->hasError(), "EXPORT_FAILED", operation ? operation->error() : "Cannot create native GIF save operation.");
      operation->operate(); operation->done();
      require(!operation->hasError(), "EXPORT_FAILED", operation->error());
      auto size = fs::file_size(temporary.data());
      require(size > 0 && size <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Encoded GIF exceeds the 32 MiB file limit.");
      std::ifstream input(temporary.data(), std::ios::binary);
      std::vector<uint8_t> bytes(size);
      input.read(reinterpret_cast<char*>(bytes.data()), bytes.size());
      require(bool(input), "IO_ERROR", "Cannot read native GIF output.");
      unlink(temporary.data());
      return bytes;
    } catch (...) { unlink(temporary.data()); throw; }
  }
  Json exportAnimation(Document* document, const Json& params) {
    auto path = filePath(params, true);
    auto format = text(params, "format", 8);
    require(format == "gif" || format == "apng", "INVALID_PARAMS", "format must be gif or apng.");
    require(path.extension() == "." + format, "INVALID_PATH", "Animation path extension must match .gif or .apng format.");
    bool loop = params.contains("loop") ? boolean(params, "loop") : true;
    bool overwrite = params.contains("overwrite") ? boolean(params, "overwrite") : false;
    int scale = params.contains("scale") ? integer(params, "scale", 1, 16) : 1;
    auto source = document->sprite();
    auto frames = animationFrames(source, params);
    size_t pixels = size_t(source->width()) * source->height() * scale * scale;
    require(pixels <= MaxPixels && pixels * frames.size() <= MaxAnimationPixels, "LIMIT_EXCEEDED", "Animation exceeds 1,048,576 pixels per frame or 8,388,608 total output pixels. Reduce frames or scale.");
    auto result = previewMetadata(document);
    result["format"] = format; result["loop"] = loop; result["scale"] = scale;
    result["outputWidth"] = source->width() * scale; result["outputHeight"] = source->height() * scale;
    result["animationFrames"] = Json::array();
    std::unique_ptr<Sprite> gif;
    LayerImage* layer = nullptr;
    if (format == "gif") {
      gif.reset(new Sprite(IMAGE_RGB, source->width() * scale, source->height() * scale, 256));
      gif->setTotalFrames(frames.size());
      layer = new LayerImage(gif.get()); gif->folder()->addLayer(layer);
    }
    automation::ApngEncoder apng(frames.size(), loop);
    for (size_t i = 0; i < frames.size(); ++i) {
      int duration = source->frameDuration(frames[i]);
      require(duration >= 1 && duration <= 65535, "INVALID_PARAMS", "Animation durations must be 1 to 65,535 ms.");
      // GIF delay fields are centiseconds. Avoid zero-delay viewer-dependent GIFs.
      require(format != "gif" || duration >= 10, "UNSUPPORTED_TIMING", "GIF requires durations of at least 10 ms. Use APNG for shorter exact timing.");
      result["animationFrames"].push_back({{"frame", frames[i]}, {"durationMs", duration}, {"encodedDurationMs", format == "gif" ? (duration / 10) * 10 : duration}});
      auto image = composite(source, frames[i]);
      if (gif) {
        ImageRef scaled(Image::create(IMAGE_RGB, gif->width(), gif->height()));
        for (int y = 0; y < scaled->height(); ++y)
          for (int x = 0; x < scaled->width(); ++x) scaled->putPixel(x, y, image->getPixel(x / scale, y / scale));
        layer->addCel(std::make_shared<Cel>(i, scaled));
        gif->setFrameDuration(i, duration);
      } else {
        try { apng.append(encodePng(image.get(), scale), duration); }
        catch (const std::length_error& error) { throw BridgeError("LIMIT_EXCEEDED", error.what()); }
        catch (const std::runtime_error& error) { throw BridgeError("EXPORT_FAILED", error.what()); }
      }
    }
    std::vector<uint8_t> bytes;
    if (gif) bytes = encodeGif(gif.release(), loop);
    else {
      try { bytes = apng.finish(); }
      catch (const std::length_error& error) { throw BridgeError("LIMIT_EXCEEDED", error.what()); }
      catch (const std::runtime_error& error) { throw BridgeError("EXPORT_FAILED", error.what()); }
    }
    result["path"] = path.lexically_relative(m_root).generic_string(); result["bytes"] = bytes.size();
    require(result.dump().size() < MaxResponse - 4096, "LIMIT_EXCEEDED", "Animation metadata exceeds the bridge limit.");
    publishExport(path, bytes, overwrite);
    return result;
  }
  Json canvas(Document* document, const Json& params, bool cropping) {
    auto sprite = document->sprite();
    int width = integer(params, "width", 1, 1024), height = integer(params, "height", 1, 1024);
    int x = cropping ? integer(params, "x", 0, sprite->width() - 1) : 0;
    int y = cropping ? integer(params, "y", 0, sprite->height() - 1) : 0;
    int dx = cropping ? -x : params.contains("offsetX") ? integer(params, "offsetX", -1023, 1023) : 0;
    int dy = cropping ? -y : params.contains("offsetY") ? integer(params, "offsetY", -1023, 1023) : 0;
    gfx::Rect bounds(x, y, width, height);
    require(!cropping || sprite->bounds().contains(bounds), "OUTSIDE_CANVAS", "Crop rectangle must be entirely inside the current canvas.");
    require(!sprite->backgroundLayer(), "UNSUPPORTED_LAYER", "Canvas operations currently require transparent layers; convert the native background explicitly first.");
    for (auto layer : sprite->layers()) editable(layer);
    struct Plan { Layer* layer; std::vector<int> frames; int x, y; bool remove; ImageRef image; };
    std::vector<Plan> plans;
    std::map<ObjectId, size_t> data;
    std::map<ObjectId, ObjectId> imageData;
    bool loss = false, contentChanged = width != sprite->width() || height != sprite->height();
    size_t scratch = 0;
    for (auto cel : sprite->cels()) {
      auto found = data.find(cel->data()->id());
      if (found != data.end()) {
        require(!cropping || plans[found->second].layer == cel->layer(), "SHARED_CEL_DATA", "Crop refuses cel data linked across different layers.");
        plans[found->second].frames.push_back(cel->frame()); continue;
      }
      auto intersection = cel->bounds() & bounds;
      bool cut = cropping && intersection != cel->bounds();
      loss |= cut; contentChanged |= cut || dx || dy;
      int nx = cut && !intersection.isEmpty() ? intersection.x + dx : cel->x() + dx;
      int ny = cut && !intersection.isEmpty() ? intersection.y + dy : cel->y() + dy;
      require((cropping && intersection.isEmpty()) || (nx >= -32768 && nx <= 32767 && ny >= -32768 && ny <= 32767), "OUTSIDE_NATIVE_RANGE", "Canvas shift would exceed native signed cel coordinates.");
      data[cel->data()->id()] = plans.size();
      plans.push_back({cel->layer(), {cel->frame()}, nx, ny, cropping && intersection.isEmpty(), {}});
      // Separate CelData objects may still share an image. Moving is harmless;
      // cropping via ReplaceImage would otherwise alter a different position.
      auto previous = imageData.find(cel->image()->id());
      require(!cropping || previous == imageData.end() || previous->second == cel->data()->id(), "SHARED_IMAGE", "Canvas crop refuses images shared by separate cel data. Make independent copies first.");
      imageData[cel->image()->id()] = cel->data()->id();
      if (cut && !intersection.isEmpty()) scratch += size_t(intersection.w) * intersection.h * (sprite->pixelFormat() == IMAGE_RGB ? 4 : sprite->pixelFormat() == IMAGE_GRAYSCALE ? 2 : 1);
    }
    auto oldMask = document->mask();
    require(cropping || oldMask->isEmpty() || (int64_t(oldMask->bounds().x) + dx >= -32768 && int64_t(oldMask->bounds().x) + dx <= 32767 && int64_t(oldMask->bounds().y) + dy >= -32768 && int64_t(oldMask->bounds().y) + dy <= 32767), "OUTSIDE_NATIVE_RANGE", "Canvas shift would exceed supported selection origins.");
    require(!cropping || oldMask->isEmpty() || document->isMaskVisible(), "HIDDEN_SELECTION", "Show or clear the retained hidden selection explicitly before cropping.");
    loss |= cropping && !oldMask->isEmpty() && !bounds.contains(oldMask->bounds());
    bool changed = contentChanged || loss || (!oldMask->isEmpty() && (dx || dy));
    bool discard = params.contains("discardOutside") ? boolean(params, "discardOutside") : false;
    require(!loss || discard, "WOULD_DISCARD_PIXELS", "Crop would discard cel data or selection bounds, including off-canvas data. Explicitly set discardOutside:true.");
    require(scratch <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Canvas crop scratch exceeds 32 MiB.");
    if (!changed) return {{"canvasChanged", false}};
    Mask mask;
    if (cropping && !oldMask->isEmpty()) {
      mask.replace(gfx::Rect(0, 0, width, height)); mask.bitmap()->clear(0);
      for (int yy = 0; yy < height; ++yy) for (int xx = 0; xx < width; ++xx)
        mask.bitmap()->putPixel(xx, yy, oldMask->containsPoint(xx + x, yy + y));
      mask.shrink();
    }
    // Finish all crop allocations before changing the model. Plans retain IDs/
    // frames rather than removed Cel refs, so rollback reconstruction is safe.
    for (auto& plan : plans) {
      auto cel = plan.layer->cel(plan.frames.front());
      if (cropping && !plan.remove) {
        auto intersection = cel->bounds() & bounds;
        if (intersection != cel->bounds()) plan.image.reset(doc::crop_image(cel->image(), intersection.x - cel->x(), intersection.y - cel->y(), intersection.w, intersection.h, sprite->transparentColor()));
      }
    }
    Transaction transaction(UIContext::instance(), cropping ? "AI crop canvas" : "AI resize canvas (preserve pixels)", contentChanged ? ModifyDocument : DoesntModifyDocument);
    for (auto& plan : plans) {
      if (plan.remove) {
        for (int frame : plan.frames) transaction.execute(new cmd::RemoveCel(plan.layer->cel(frame)));
      } else {
        auto cel = plan.layer->cel(plan.frames.front());
        if (plan.image) transaction.execute(new cmd::ReplaceImage(sprite, cel->imageRef(), plan.image));
        if (plan.x != cel->x() || plan.y != cel->y()) transaction.execute(new cmd::SetCelPosition(cel, plan.x, plan.y));
      }
    }
    if (width != sprite->width() || height != sprite->height()) transaction.execute(new cmd::SetSpriteSize(sprite, width, height));
    if (!oldMask->isEmpty()) {
      if (cropping && !sameSelection(document, mask)) transaction.execute(new cmd::SetMask(document, &mask));
      else if (!cropping && (dx || dy)) transaction.execute(new cmd::SetMaskPosition(document, gfx::Point(oldMask->bounds().x + dx, oldMask->bounds().y + dy)));
    }
    finish(transaction, document);
    document->generateMaskBoundaries();
    return {{"canvasChanged", true}, {"discardedOutside", loss}, {"offsetX", dx}, {"offsetY", dy}};
  }
  LayerFolder* destinationParent(Sprite* sprite, const Json& params, LayerFolder* fallback) {
    if (!params.contains("parentId")) return fallback;
    auto layer = params["parentId"].is_null() ? sprite->folder() : findLayer(sprite, integer(params, "parentId", 1, INT32_MAX));
    require(layer->isFolder(), "INVALID_PARAMS", "parentId must identify a group, or null for root.");
    return static_cast<LayerFolder*>(layer);
  }
  Layer* insertionAfter(Sprite* sprite, LayerFolder* parent, const Json& params, Layer* fallback) {
    auto after = !params.contains("afterLayerId") ? fallback : params["afterLayerId"].is_null() ? nullptr : findLayer(sprite, integer(params, "afterLayerId", 1, INT32_MAX));
    require(!after || after->parent() == parent, "INVALID_PARAMS", "Insertion reference must be a sibling in the destination group.");
    require(after || !parent->getFirstLayer() || !parent->getFirstLayer()->isBackground(), "UNSUPPORTED_LAYER", "Cannot insert below a background layer.");
    return after;
  }
  std::unique_ptr<Layer> cloneLayer(Sprite* sprite, Layer* source) {
    std::unique_ptr<Layer> result(source->isImage() ? static_cast<Layer*>(new LayerImage(sprite)) : static_cast<Layer*>(new LayerFolder(sprite)));
    result->setName(source->name()); result->setFlags(source->flags()); result->setUserData(source->userData());
    if (source->isImage()) {
      auto target = static_cast<LayerImage*>(result.get()), original = static_cast<LayerImage*>(source);
      target->setOpacity(original->opacity()); target->setBlendMode(original->blendMode());
      for (auto it = original->getCelBegin(); it != original->getCelEnd(); ++it) target->addCel(rawCelCopy(*it, (*it)->frame()));
    } else {
      auto folder = static_cast<LayerFolder*>(result.get());
      for (auto child : static_cast<LayerFolder*>(source)->getLayersList()) {
        auto copy = cloneLayer(sprite, child); folder->addLayer(copy.get()); copy.release();
      }
    }
    return result;
  }
  Json duplicateLayer(Document* document, const Json& params) {
    auto sprite = document->sprite();
    auto source = findLayer(sprite, integer(params, "layerId", 1, INT32_MAX));
    auto parent = destinationParent(sprite, params, source->parent());
    editable(parent);
    auto after = insertionAfter(sprite, parent, params, parent == source->parent() ? source : parent->getLastLayer());
    int count = 0; size_t bytes = 0;
    auto countSource = [&](auto&& visit, Layer* layer) -> void {
      ++count; require(!layer->isBackground(), "UNSUPPORTED_LAYER", "Duplicating a background layer is not supported; convert it explicitly first.");
      if (layer->isImage()) {
        CelList cels; layer->getCels(cels); for (auto cel : cels) bytes += imageBytes(cel->image());
      } else for (auto child : static_cast<LayerFolder*>(layer)->getLayersList()) visit(visit, child);
    };
    countSource(countSource, source);
    require(sprite->countLayers() + count <= 128, "LIMIT_EXCEEDED", "Layer copies exceed the 128-layer limit.");
    require(spriteBytes(sprite) + bytes <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Independent layer copies exceed the 32 MiB working limit.");
    auto copy = cloneLayer(sprite, source);
    copy->setName(params.contains("name") ? text(params, "name", 120) : source->name() + " Copy");
    auto id = copy->id();
    Transaction transaction(UIContext::instance(), "AI duplicate layer subtree");
    transaction.execute(new cmd::AddLayer(parent, copy.get(), after)); copy.release();
    finish(transaction, document);
    UIContext::instance()->activeEditor()->setLayer(findLayer(sprite, id));
    return {{"createdLayerId", id}, {"copiedLayerCount", count}};
  }
  Json reparentLayer(Document* document, const Json& params) {
    auto sprite = document->sprite();
    auto layer = findLayer(sprite, integer(params, "layerId", 1, INT32_MAX));
    editable(layer);
    require(layer->isMovable() && !layer->isBackground(), "UNSUPPORTED_LAYER", "Target layer is movement-locked or a background.");
    require(params.contains("parentId"), "INVALID_PARAMS", "Supply destination parentId (null for root).");
    auto parent = destinationParent(sprite, params, layer->parent());
    editable(parent);
    for (auto ancestor = static_cast<Layer*>(parent); ancestor; ancestor = ancestor->parent()) require(ancestor != layer, "LAYER_CYCLE", "Cannot put a group inside itself or its descendants.");
    auto after = insertionAfter(sprite, parent, params, parent == layer->parent() ? layer->getPrevious() : parent->getLastLayer());
    require(after != layer, "INVALID_PARAMS", "A layer cannot be its own insertion reference.");
    if (parent == layer->parent() && after == layer->getPrevious()) return {{"reparented", false}};
    Transaction transaction(UIContext::instance(), "AI reparent layer");
    if (parent == layer->parent()) transaction.execute(new cmd::MoveLayer(layer, after));
    else transaction.execute(new automation::ReparentLayer(layer, parent, after));
    finish(transaction, document);
    return {{"reparented", true}};
  }
  Layer* celLayer(Document* document, const Json& params, bool allowLinked = false) {
    auto sprite = document->sprite();
    auto target = findLayer(sprite, integer(params, "layerId", 1, INT32_MAX));
    require(target->isImage(), "UNSUPPORTED_LAYER", "An image layer is required for cel operations.");
    editable(target);
    require(!target->isBackground(), "UNSUPPORTED_LAYER", "Cel operations currently require a transparent layer.");
    auto frame = integer(params, "frame", 0, sprite->totalFrames() - 1);
    auto cel = target->cel(frame);
    require(allowLinked || !cel || cel->links() == 0, "LINKED_CEL", "Unlink the cel before editing; implicit edits across frames are refused.");
    return target;
  }
  void independentImage(Sprite* sprite, const std::shared_ptr<Cel>& cel) {
    if (!cel) return;
    for (auto other : sprite->cels())
      require(other == cel || other->image()->id() != cel->image()->id(), "SHARED_IMAGE", "Another cel shares this image. Make an independent copy before changing pixels.");
  }
  Layer* paintLayer(Document* document, const Json& params) {
    require(document->sprite()->pixelFormat() == IMAGE_RGB, "UNSUPPORTED_COLOR_MODE", "Pixel edits currently require RGBA sprites.");
    auto target = celLayer(document, params);
    independentImage(document->sprite(), target->cel(integer(params, "frame", 0, document->sprite()->lastFrame())));
    return target;
  }
  size_t imageBytes(const Image* image) { return size_t(image->getRowStrideSize()) * image->height(); }
  size_t spriteBytes(Sprite* sprite) {
    std::vector<Image*> images; sprite->getImages(images);
    size_t bytes = 0;
    for (auto image : images) bytes += imageBytes(image);
    return bytes;
  }
  std::vector<int> uniqueFrames(Sprite* sprite, const Json& params, const char* key = "frames") {
    require(params.contains(key) && params[key].is_array() && !params[key].empty() && params[key].size() <= 256, "INVALID_PARAMS", "Supply 1 to 256 unique frame indices.");
    std::vector<int> frames;
    for (auto value : params[key]) {
      int frame = integer({{"frame", value}}, "frame", 0, sprite->lastFrame());
      require(std::find(frames.begin(), frames.end(), frame) == frames.end(), "INVALID_PARAMS", "Frame indices must be unique.");
      frames.push_back(frame);
    }
    return frames;
  }
  std::shared_ptr<Cel> rawCelCopy(const std::shared_ptr<Cel>& source, int frame) {
    auto copy = Cel::createCopy(source);
    copy->setFrame(frame);
    copy->data()->setUserData(source->data()->userData());
    return copy;
  }
  Json copyCel(Document* document, const Json& params) {
    auto sprite = document->sprite();
    auto source = findLayer(sprite, integer(params, "sourceLayerId", 1, INT32_MAX));
    require(source->isImage(), "UNSUPPORTED_LAYER", "Cel copy source must be an image layer.");
    int from = integer(params, "sourceFrame", 0, sprite->lastFrame());
    auto cel = source->cel(from);
    require(bool(cel), "CEL_NOT_FOUND", "Source cel is missing; copying empty frames is not an erase operation.");
    auto target = celLayer(document, params);
    int frame = integer(params, "frame", 0, sprite->lastFrame());
    bool overwrite = params.contains("overwrite") ? boolean(params, "overwrite") : false;
    if (source == target && from == frame) return {{"copied", false}};
    auto previous = target->cel(frame);
    independentImage(sprite, previous);
    require(!previous || overwrite, "CEL_EXISTS", "Destination cel exists. Explicitly allow replacement with overwrite:true.");
    require(sprite->pixelFormat() != IMAGE_INDEXED || sprite->palette(from)->countDiff(*sprite->palette(frame), nullptr, nullptr) == 0,
            "UNSUPPORTED_PALETTES", "Indexed cel copies require identical source/destination palettes. Silent remapping is refused.");
    size_t predicted = spriteBytes(sprite) + imageBytes(cel->image()) - (previous ? imageBytes(previous->image()) : 0);
    require(predicted <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Independent cel copy exceeds the 32 MiB working limit.");
    auto copied = rawCelCopy(cel, frame);
    Transaction transaction(UIContext::instance(), "AI copy cel");
    if (previous) transaction.execute(new cmd::RemoveCel(previous));
    transaction.execute(new cmd::AddCel(target, copied));
    finish(transaction, document);
    UIContext::instance()->activeEditor()->setLayer(target);
    UIContext::instance()->activeEditor()->setFrame(frame);
    return {{"copied", true}, {"sourceLayerId", source->id()}, {"sourceFrame", from}, {"destinationFrame", frame}};
  }
  Json duplicateFrames(Document* document, const Json& params) {
    auto sprite = document->sprite();
    auto frames = uniqueFrames(sprite, params);
    int index = integer(params, "index", 0, sprite->totalFrames());
    require(sprite->totalFrames() + frames.size() <= 256, "LIMIT_EXCEEDED", "Duplication exceeds the 256-frame limit.");
    require(sprite->getPalettes().size() == 1, "UNSUPPORTED_PALETTES", "Frame duplication with palette keyframes is not supported.");
    size_t copiedBytes = 0;
    for (auto layer : sprite->layers()) {
      editable(layer);
      if (layer->isImage()) for (int frame : frames) if (auto cel = layer->cel(frame)) copiedBytes += imageBytes(cel->image());
    }
    // Reserve a native background insertion scratch canvas too, if applicable.
    size_t scratch = sprite->backgroundLayer() ? size_t(sprite->width()) * sprite->height() * 4 : 0;
    require(spriteBytes(sprite) + copiedBytes + scratch <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Frame copies/scratch exceed the 32 MiB working limit.");
    struct Copy { Layer* layer; std::shared_ptr<Cel> cel; };
    std::vector<Copy> copies;
    std::vector<int> durations;
    // Snapshot every source BEFORE insertion shifts indices; never copy from a
    // newly inserted frame or silently preserve links/continuous preferences.
    for (size_t i = 0; i < frames.size(); ++i) {
      durations.push_back(sprite->frameDuration(frames[i]));
      for (auto layer : sprite->layers()) if (layer->isImage()) if (auto cel = layer->cel(frames[i]))
        copies.push_back({layer, rawCelCopy(cel, index + i)});
    }
    Transaction transaction(UIContext::instance(), "AI duplicate frame range");
    auto api = document->getApi(transaction);
    for (size_t i = 0; i < frames.size(); ++i) {
      api.addEmptyFrame(sprite, index + i);
      transaction.execute(new cmd::SetFrameDuration(sprite, index + i, durations[i]));
    }
    for (auto& copy : copies) {
      if (auto blank = copy.layer->cel(copy.cel->frame())) transaction.execute(new cmd::RemoveCel(blank));
      transaction.execute(new cmd::AddCel(copy.layer, copy.cel));
    }
    finish(transaction, document);
    UIContext::instance()->activeEditor()->setFrame(index);
    return {{"insertedFrom", index}, {"insertedCount", frames.size()}, {"sourceFrames", frames}};
  }
  Json reorderFrames(Document* document, const Json& params) {
    auto sprite = document->sprite();
    auto order = uniqueFrames(sprite, params, "order");
    require(order.size() == size_t(sprite->totalFrames()), "INVALID_PARAMS", "order must include every current frame exactly once (new index -> old index).");
    require(sprite->getPalettes().size() == 1, "UNSUPPORTED_PALETTES", "Frame reordering with palette keyframes is not supported.");
    for (auto layer : sprite->layers()) editable(layer);
    std::vector<int> inverse(order.size());
    bool changed = false;
    for (size_t i = 0; i < order.size(); ++i) { inverse[order[i]] = i; changed |= order[i] != int(i); }
    struct TagRange { FrameTag* tag; int from, to; };
    std::vector<TagRange> ranges;
    for (auto tag : sprite->frameTags()) {
      int from = sprite->totalFrames(), to = -1;
      require(tag->fromFrame() >= 0 && tag->toFrame() <= sprite->lastFrame() && tag->fromFrame() <= tag->toFrame(), "INVALID_PARAMS", "Invalid tag range.");
      for (int i = tag->fromFrame(); i <= tag->toFrame(); ++i) { from = std::min(from, inverse[i]); to = std::max(to, inverse[i]); }
      require(to - from == tag->toFrame() - tag->fromFrame(), "TAG_SPLIT", "Reorder would split a tag's original frames into disjoint ranges. Update/remove that tag explicitly first.");
      ranges.push_back({tag, from, to});
    }
    if (!changed) return {{"reordered", false}, {"order", order}};
    auto editor = UIContext::instance()->activeEditor();
    int frame = inverse[editor->frame()];
    Transaction transaction(UIContext::instance(), "AI reorder frames");
    transaction.execute(new automation::ReorderFrames(sprite, order));
    for (const auto& range : ranges) if (range.from != range.tag->fromFrame() || range.to != range.tag->toFrame())
      transaction.execute(new cmd::SetFrameTagRange(range.tag, range.from, range.to));
    finish(transaction, document);
    editor->setFrame(frame);
    return {{"reordered", true}, {"order", order}, {"oldToNew", inverse}};
  }
  std::string transformOperation(const Json& params) {
    auto operation = text(params, "operation", 32);
    require(operation == "flip_horizontal" || operation == "flip_vertical" || operation == "rotate_cw" || operation == "rotate_ccw" || operation == "rotate_180", "INVALID_PARAMS", "Choose an exact flip/quarter-turn/180-degree transform.");
    return operation;
  }
  gfx::Point transformedPoint(int x, int y, int w, int h, const std::string& operation) {
    if (operation == "flip_horizontal") return gfx::Point(w - 1 - x, y);
    if (operation == "flip_vertical") return gfx::Point(x, h - 1 - y);
    if (operation == "rotate_cw") return gfx::Point(h - 1 - y, x);
    if (operation == "rotate_ccw") return gfx::Point(y, w - 1 - x);
    return gfx::Point(w - 1 - x, h - 1 - y);
  }
  ImageRef transformedImage(const Image* image, const std::string& operation) {
    require(image->width() <= 1024 && image->height() <= 1024, "LIMIT_EXCEEDED", "Whole-cel transforms support image bounds of at most 1024x1024.");
    bool quarter = operation == "rotate_cw" || operation == "rotate_ccw";
    ImageRef result(Image::create(image->pixelFormat(), quarter ? image->height() : image->width(), quarter ? image->width() : image->height()));
    result->setMaskColor(image->maskColor());
    for (int y = 0; y < image->height(); ++y) for (int x = 0; x < image->width(); ++x) {
      auto p = transformedPoint(x, y, image->width(), image->height(), operation);
      result->putPixel(p.x, p.y, image->getPixel(x, y));
    }
    return result;
  }
  Json editCels(Document* document, const Json& params) {
    auto sprite = document->sprite();
    require(params.contains("edits") && params["edits"].is_array() && !params["edits"].empty() && params["edits"].size() <= 256, "INVALID_PARAMS", "Supply 1 to 256 explicit cel edits.");
    struct Edit { std::shared_ptr<Cel> cel; int x, y, opacity; std::string operation; ImageRef image; };
    std::vector<Edit> edits;
    size_t scratch = 0;
    for (const auto& entry : params["edits"]) {
      auto layer = celLayer(document, entry);
      int frame = integer(entry, "frame", 0, sprite->lastFrame());
      auto cel = layer->cel(frame);
      require(bool(cel), "CEL_NOT_FOUND", "Every batch target must have an existing cel.");
      for (const auto& edit : edits) require(edit.cel != cel, "INVALID_PARAMS", "Each layer/frame can occur only once per batch.");
      require(entry.contains("x") || entry.contains("y") || entry.contains("opacity") || entry.contains("operation"), "INVALID_PARAMS", "Each cel edit needs x, y, opacity, and/or operation.");
      Edit edit{cel, entry.contains("x") ? integer(entry, "x", -32768, 32767) : cel->x(),
                entry.contains("y") ? integer(entry, "y", -32768, 32767) : cel->y(),
                entry.contains("opacity") ? integer(entry, "opacity", 0, 255) : cel->opacity(), "", {}};
      if (entry.contains("operation")) {
        edit.operation = transformOperation(entry);
        independentImage(sprite, cel);
        require(cel->image()->width() <= 1024 && cel->image()->height() <= 1024, "LIMIT_EXCEEDED", "Batch transforms support cel bounds up to 1024x1024.");
        scratch += imageBytes(cel->image());
      }
      edits.push_back(std::move(edit));
    }
    require(scratch <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Batch transform scratch exceeds 32 MiB.");
    bool changed = false;
    for (auto& edit : edits) {
      if (!edit.operation.empty()) {
        edit.image = transformedImage(edit.cel->image(), edit.operation);
        if (edit.image->size() == edit.cel->image()->size() && doc::count_diff_between_images(edit.image.get(), edit.cel->image()) == 0) edit.image.reset();
      }
      changed |= bool(edit.image) || edit.x != edit.cel->x() || edit.y != edit.cel->y() || edit.opacity != edit.cel->opacity();
    }
    if (!changed) return {{"editedCels", 0}};
    Transaction transaction(UIContext::instance(), "AI atomic cel batch");
    int count = 0;
    for (auto& edit : edits) {
      bool differs = bool(edit.image) || edit.x != edit.cel->x() || edit.y != edit.cel->y() || edit.opacity != edit.cel->opacity();
      if (!differs) continue;
      ++count;
      if (edit.image) transaction.execute(new cmd::ReplaceImage(sprite, edit.cel->imageRef(), edit.image));
      if (edit.x != edit.cel->x() || edit.y != edit.cel->y()) transaction.execute(new cmd::SetCelPosition(edit.cel, edit.x, edit.y));
      if (edit.opacity != edit.cel->opacity()) transaction.execute(new cmd::SetCelOpacity(edit.cel, edit.opacity));
    }
    finish(transaction, document);
    return {{"editedCels", count}};
  }
  Json frameDurations(Document* document, const Json& params) {
    auto sprite = document->sprite();
    require(params.contains("durations") && params["durations"].is_array() && !params["durations"].empty() && params["durations"].size() <= 256, "INVALID_PARAMS", "Supply 1 to 256 frame/duration pairs.");
    std::vector<std::pair<int, int>> durations;
    int count = 0;
    for (const auto& entry : params["durations"]) {
      int frame = integer(entry, "frame", 0, sprite->lastFrame()), duration = integer(entry, "durationMs", 1, 65535);
      for (auto other : durations) require(other.first != frame, "INVALID_PARAMS", "Each frame can occur only once per timing batch.");
      durations.push_back({frame, duration});
      if (sprite->frameDuration(frame) != duration) ++count;
    }
    if (!count) return {{"editedDurations", 0}};
    Transaction transaction(UIContext::instance(), "AI atomic frame timing");
    for (auto pair : durations) if (sprite->frameDuration(pair.first) != pair.second)
      transaction.execute(new cmd::SetFrameDuration(sprite, pair.first, pair.second));
    finish(transaction, document);
    return {{"editedDurations", count}};
  }
  void editCel(Document* document, const Json& params, const std::string& method) {
    auto sprite = document->sprite();
    auto target = celLayer(document, params, method == "unlink_cel");
    int frame = integer(params, "frame", 0, sprite->lastFrame());
    auto cel = target->cel(frame);
    require(bool(cel), "CEL_NOT_FOUND", "No cel exists on this layer/frame.");
    if (method == "unlink_cel") {
      if (!cel->links()) return;
      UIContext::instance()->activeEditor()->setLayer(target);
      UIContext::instance()->activeEditor()->setFrame(frame);
      Transaction transaction(UIContext::instance(), "AI unlink cel");
      transaction.execute(new cmd::UnlinkCel(cel));
      finish(transaction, document);
      return;
    }
    if (method == "update_cel") {
      require(params.contains("x") || params.contains("y") || params.contains("opacity"), "INVALID_PARAMS", "Provide cel x, y, and/or opacity.");
      int x = params.contains("x") ? integer(params, "x", -32768, 32767) : cel->x();
      int y = params.contains("y") ? integer(params, "y", -32768, 32767) : cel->y();
      int opacity = params.contains("opacity") ? integer(params, "opacity", 0, 255) : cel->opacity();
      if (x == cel->x() && y == cel->y() && opacity == cel->opacity()) return;
      UIContext::instance()->activeEditor()->setLayer(target);
      UIContext::instance()->activeEditor()->setFrame(frame);
      Transaction transaction(UIContext::instance(), "AI cel properties");
      if (x != cel->x() || y != cel->y()) transaction.execute(new cmd::SetCelPosition(cel, x, y));
      if (opacity != cel->opacity()) transaction.execute(new cmd::SetCelOpacity(cel, opacity));
      finish(transaction, document);
      return;
    }
    independentImage(sprite, cel);
    auto operation = transformOperation(params);
    auto image = cel->image();
    auto transformed = transformedImage(image, operation);
    if (transformed->size() == image->size() && doc::count_diff_between_images(image, transformed.get()) == 0) return;
    UIContext::instance()->activeEditor()->setLayer(target);
    UIContext::instance()->activeEditor()->setFrame(frame);
    Transaction transaction(UIContext::instance(), "AI cel transform");
    transaction.execute(new cmd::ReplaceImage(sprite, cel->imageRef(), transformed));
    finish(transaction, document);
  }
  Mask* visibleSelection(Document* document) {
    require(document->isMaskVisible() && selectionInfo(document)["selectedPixels"] != 0, "NO_SELECTION", "A visible nonempty selection is required. Refusing a whole-cel fallback.");
    return document->mask();
  }
  Mask* paintSelection(Document* document, const Json& params) {
    return params.contains("respectSelection") && boolean(params, "respectSelection") ? visibleSelection(document) : nullptr;
  }
  bool sameSelection(Document* document, const Mask& mask) {
    if (!document->isMaskVisible()) return mask.isEmpty();
    auto current = document->mask();
    return !mask.isEmpty() && current->bounds() == mask.bounds() && doc::count_diff_between_images(current->bitmap(), mask.bitmap()) == 0;
  }
  void editSelection(Document* document, const Json& params, bool modifying) {
    auto sprite = document->sprite();
    Mask mask;
    mask.replace(sprite->bounds()); mask.bitmap()->clear(0);
    if (modifying) {
      auto action = text(params, "action", 16);
      require(action == "all" || action == "none" || action == "invert", "INVALID_PARAMS", "action must be all, none, or invert.");
      for (int y = 0; y < sprite->height(); ++y)
        for (int x = 0; x < sprite->width(); ++x)
          mask.bitmap()->putPixel(x, y, action == "all" || (action == "invert" && !(document->isMaskVisible() && document->mask()->containsPoint(x, y))));
    } else {
      auto mode = params.contains("mode") ? text(params, "mode", 16) : "replace";
      auto shape = params.contains("shape") ? text(params, "shape", 16) : "rectangle";
      require(mode == "replace" || mode == "add" || mode == "subtract" || mode == "intersect", "INVALID_PARAMS", "mode must be replace, add, subtract, or intersect.");
      require(shape == "rectangle" || shape == "ellipse", "INVALID_PARAMS", "shape must be rectangle or ellipse.");
      int x1 = integer(params, "x1", 0, sprite->width() - 1), y1 = integer(params, "y1", 0, sprite->height() - 1);
      int x2 = integer(params, "x2", 0, sprite->width() - 1), y2 = integer(params, "y2", 0, sprite->height() - 1);
      if (x1 > x2) std::swap(x1, x2);
      if (y1 > y2) std::swap(y1, y2);
      if (shape == "rectangle") doc::fill_rect(mask.bitmap(), x1, y1, x2, y2, 1);
      else doc::fill_ellipse(mask.bitmap(), x1, y1, x2, y2, 1);
      if (mode != "replace") {
        for (int y = 0; y < sprite->height(); ++y)
          for (int x = 0; x < sprite->width(); ++x) {
            bool old = document->isMaskVisible() && document->mask()->containsPoint(x, y), added = mask.containsPoint(x, y);
            mask.bitmap()->putPixel(x, y, mode == "add" ? old || added : mode == "subtract" ? old && !added : old && added);
          }
      }
    }
    mask.shrink();
    if (sameSelection(document, mask)) return;
    Transaction transaction(UIContext::instance(), "AI selection", DoesntModifyDocument);
    transaction.execute(new cmd::SetMask(document, &mask));
    finish(transaction, document);
    document->generateMaskBoundaries();
  }
  void advancedSelection(Document* document, const Json& params, bool polygon) {
    auto sprite = document->sprite();
    auto mode = params.contains("mode") ? text(params, "mode", 16) : "replace";
    require(mode == "replace" || mode == "add" || mode == "subtract" || mode == "intersect", "INVALID_PARAMS", "mode must be replace, add, subtract, or intersect.");
    Mask mask; mask.replace(sprite->bounds()); mask.bitmap()->clear(0);
    if (polygon) {
      require(params.contains("vertices") && params["vertices"].is_array() && params["vertices"].size() >= 3 && params["vertices"].size() <= 128, "INVALID_PARAMS", "Polygon requires 3 to 128 vertices.");
      std::vector<gfx::Point> points, distinct;
      gfx::Rect bounds;
      for (const auto& vertex : params["vertices"]) {
        gfx::Point p(integer(vertex, "x", 0, sprite->width() - 1), integer(vertex, "y", 0, sprite->height() - 1));
        points.push_back(p); bounds |= gfx::Rect(p.x, p.y, 1, 1);
        if (std::find(distinct.begin(), distinct.end(), p) == distinct.end()) distinct.push_back(p);
      }
      require(distinct.size() >= 3, "INVALID_PARAMS", "Polygon requires at least three distinct vertices.");
      require(size_t(bounds.w) * bounds.h * points.size() <= 8 * 1024 * 1024, "LIMIT_EXCEEDED", "Polygon exceeds 8,388,608 pixel-edge tests.");
      // Even-odd fill at pixel centers, plus inclusive native one-pixel edges.
      // Self-intersections are explicit even-odd regions, never antialiased.
      for (int y = bounds.y; y < bounds.y2(); ++y) for (int x = bounds.x; x < bounds.x2(); ++x) {
        bool inside = false;
        double px = x + 0.5, py = y + 0.5;
        for (size_t i = 0, j = points.size() - 1; i < points.size(); j = i++) {
          const auto& a = points[i]; const auto& b = points[j];
          if ((a.y > py) != (b.y > py) && px < a.x + (py - a.y) * (b.x - a.x) / (b.y - a.y)) inside = !inside;
        }
        if (inside) mask.bitmap()->putPixel(x, y, 1);
      }
      for (size_t i = 0; i < points.size(); ++i) {
        const auto& a = points[i]; const auto& b = points[(i + 1) % points.size()];
        doc::draw_line(mask.bitmap(), a.x, a.y, b.x, b.y, 1);
      }
    } else {
      int x = integer(params, "x", 0, sprite->width() - 1), y = integer(params, "y", 0, sprite->height() - 1);
      int width = integer(params, "width", 1, 1024), height = integer(params, "height", 1, 1024);
      auto bits = text(params, "bits", 262144);
      require(sprite->bounds().contains(gfx::Rect(x, y, width, height)), "OUTSIDE_CANVAS", "Bitmap selection must fit the canvas.");
      require(bits.size() == size_t(width * height) && bits.find_first_not_of("01") == std::string::npos, "INVALID_PARAMS", "Mask bits must be exactly width*height binary digits, row-major (at most 262,144).");
      for (int yy = 0; yy < height; ++yy) for (int xx = 0; xx < width; ++xx) mask.bitmap()->putPixel(x + xx, y + yy, bits[yy * width + xx] == '1');
    }
    if (mode != "replace") for (int y = 0; y < sprite->height(); ++y) for (int x = 0; x < sprite->width(); ++x) {
      bool old = document->isMaskVisible() && document->mask()->containsPoint(x, y), added = mask.containsPoint(x, y);
      mask.bitmap()->putPixel(x, y, mode == "add" ? old || added : mode == "subtract" ? old && !added : old && added);
    }
    mask.shrink();
    if (sameSelection(document, mask)) return;
    Transaction transaction(UIContext::instance(), polygon ? "AI polygon selection" : "AI bitmap selection", DoesntModifyDocument);
    transaction.execute(new cmd::SetMask(document, &mask));
    finish(transaction, document); document->generateMaskBoundaries();
  }
  Json renderSelection(Document* document, const Json& params) {
    auto sprite = document->sprite();
    int frame = integer(params, "frame", 0, sprite->lastFrame());
    int scale = params.contains("scale") ? integer(params, "scale", 1, 16) : 1;
    require(size_t(sprite->width()) * sprite->height() * scale * scale <= MaxPixels, "LIMIT_EXCEEDED", "Selection preview exceeds 1,048,576 output pixels.");
    auto mode = params.contains("mode") ? text(params, "mode", 16) : "overlay";
    require(mode == "overlay" || mode == "mask", "INVALID_PARAMS", "mode must be overlay or mask.");
    int opacity = params.contains("opacity") ? integer(params, "opacity", 0, 255) : 96;
    auto image = composite(sprite, frame);
    for (int y = 0; y < sprite->height(); ++y)
      for (int x = 0; x < sprite->width(); ++x) {
        bool selected = document->isMaskVisible() && document->mask()->containsPoint(x, y);
        if (mode == "mask") image->putPixel(x, y, selected ? rgba(255, 255, 255, 255) : 0);
        else if (selected && opacity > 0) image->putPixel(x, y, rgba_blender_normal(image->getPixel(x, y), rgba(0, 220, 255, 255), opacity));
      }
    auto result = previewMetadata(document);
    result["selection"] = selectionInfo(document); result["frame"] = frame; result["scale"] = scale; result["mode"] = mode; result["opacity"] = opacity;
    result["outputWidth"] = sprite->width() * scale; result["outputHeight"] = sprite->height() * scale;
    addPng(result, encodePng(image.get(), scale));
    return result;
  }
  void finish(Transaction& transaction, Document* document) {
    // Check before commit, so a large structural edit rolls back rather than
    // committing an uninspectable document and returning an ambiguous error.
    workingLimits(document);
    require(details(document).dump().size() < MaxResponse - 4096, "LIMIT_EXCEEDED", "Document metadata exceeds the bridge limit.");
    transaction.commit();
    document->notifyGeneralUpdate();
  }
  void applyPatch(Document* document, Layer* target, frame_t frame,
                  const ImageRef& patch, const gfx::Region& region,
                  const gfx::Point& position, const std::string& label, Mask* selection = nullptr) {
    bool maskChanged = selection && !sameSelection(document, *selection);
    if (region.isEmpty() && !maskChanged) return;
    auto cel = target->cel(frame);
    if (!region.isEmpty() && cel) {
      // Large signed cel offsets can otherwise make CropCel allocate gigabytes
      // BEFORE finish() can enforce the working limit. Bound the union up front.
      auto bounds = cel->bounds() | gfx::Rect(region.bounds()).offset(position);
      auto format = document->sprite()->pixelFormat();
      uint64_t grown = uint64_t(bounds.w) * uint64_t(bounds.h) * (format == IMAGE_RGB ? 4 : format == IMAGE_GRAYSCALE ? 2 : 1);
      require(grown <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Patch would grow an off-canvas cel beyond the 32 MiB working limit.");
      std::vector<Image*> images; document->sprite()->getImages(images);
      uint64_t total = grown;
      for (auto image : images) if (image != cel->image()) total += uint64_t(image->getRowStrideSize()) * image->height();
      require(total <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Patch would exceed the sprite's 32 MiB image working limit.");
    }
    // An absent cel has no image to preserve, but the patch's unpainted pixels
    // must be transparent (including holes in shapes).
    UIContext::instance()->activeEditor()->setLayer(target);
    UIContext::instance()->activeEditor()->setFrame(frame);
    Transaction transaction(UIContext::instance(), label, region.isEmpty() ? DoesntModifyDocument : ModifyDocument);
    if (!region.isEmpty() && cel) transaction.execute(new cmd::PatchCel(cel, patch.get(), region, position));
    else if (!region.isEmpty()) {
      auto created = std::make_shared<Cel>(frame, patch);
      created->setPosition(position);
      transaction.execute(new cmd::AddCel(target, created));
    }
    if (maskChanged) transaction.execute(new cmd::SetMask(document, selection));
    finish(transaction, document);
    if (maskChanged) document->generateMaskBoundaries();
  }
  void setPixels(Document* document, const Json& params) {
    auto sprite = document->sprite();
    auto target = paintLayer(document, params);
    auto frame = integer(params, "frame", 0, sprite->totalFrames() - 1);
    auto selection = paintSelection(document, params);
    require(params.contains("pixels") && params["pixels"].is_array() && !params["pixels"].empty() && params["pixels"].size() <= 16384,
            "INVALID_PARAMS", "Provide between 1 and 16,384 pixels.");
    struct Pixel { int x, y; color_t color; };
    std::vector<Pixel> pixels;
    gfx::Rect bounds;
    for (const auto& pixel : params["pixels"]) {
      auto x = integer(pixel, "x", 0, sprite->width() - 1), y = integer(pixel, "y", 0, sprite->height() - 1);
      auto color = rgba(integer(pixel, "r", 0, 255), integer(pixel, "g", 0, 255), integer(pixel, "b", 0, 255), integer(pixel, "a", 0, 255));
      pixels.push_back({x, y, color}); bounds |= gfx::Rect(x, y, 1, 1);
    }
    // Build an off-document patch first; validation errors never partially edit.
    ImageRef patch(Image::create(IMAGE_RGB, bounds.w, bounds.h));
    patch->clear(0);
    gfx::Region region;
    for (const auto& pixel : pixels) {
      if (selection && !selection->containsPoint(pixel.x, pixel.y)) continue;
      patch->putPixel(pixel.x - bounds.x, pixel.y - bounds.y, pixel.color);
      region |= gfx::Region(gfx::Rect(pixel.x - bounds.x, pixel.y - bounds.y, 1, 1));
    }
    auto label = params.contains("label") ? text(params, "label", 120) : "AI pixel edit";
    applyPatch(document, target, frame, patch, region, gfx::Point(bounds.x, bounds.y), label);
  }
  Layer* indexedLayer(Document* document, const Json& params) {
    require(document->sprite()->pixelFormat() == IMAGE_INDEXED, "UNSUPPORTED_COLOR_MODE", "This operation requires an indexed sprite.");
    auto layer = celLayer(document, params);
    independentImage(document->sprite(), layer->cel(integer(params, "frame", 0, document->sprite()->lastFrame())));
    return layer;
  }
  color_t indexedColor(Sprite* sprite, int frame, const Json& params) {
    int index = integer(params, "index", 0, 255);
    require(index == sprite->transparentColor() || index < sprite->palette(frame)->size(), "PALETTE_INDEX_OUT_OF_RANGE", "Index must exist in this frame's palette, or be the sprite's transparent index.");
    return index;
  }
  void indexedPixels(Document* document, const Json& params) {
    auto sprite = document->sprite();
    auto layer = indexedLayer(document, params);
    int frame = integer(params, "frame", 0, sprite->lastFrame());
    auto selection = paintSelection(document, params);
    require(params.contains("pixels") && params["pixels"].is_array() && !params["pixels"].empty() && params["pixels"].size() <= 16384, "INVALID_PARAMS", "Provide 1 to 16,384 indexed pixels.");
    std::map<std::pair<int, int>, color_t> pixels;
    gfx::Rect bounds;
    for (const auto& pixel : params["pixels"]) {
      int x = integer(pixel, "x", 0, sprite->width() - 1), y = integer(pixel, "y", 0, sprite->height() - 1);
      auto paint = indexedColor(sprite, frame, pixel);
      if (selection && !selection->containsPoint(x, y)) continue;
      pixels[{x, y}] = paint; bounds |= gfx::Rect(x, y, 1, 1);
    }
    if (pixels.empty()) return;
    ImageRef patch(Image::create(IMAGE_INDEXED, bounds.w, bounds.h));
    patch->setMaskColor(sprite->transparentColor()); patch->clear(sprite->transparentColor());
    auto cel = layer->cel(frame);
    gfx::Region region;
    for (const auto& pixel : pixels) {
      int x = pixel.first.first, y = pixel.first.second;
      auto old = cel && cel->bounds().contains(x, y) ? cel->image()->getPixel(x - cel->x(), y - cel->y()) : sprite->transparentColor();
      if (old == pixel.second) continue;
      patch->putPixel(x - bounds.x, y - bounds.y, pixel.second);
      region |= gfx::Region(gfx::Rect(x - bounds.x, y - bounds.y, 1, 1));
    }
    applyPatch(document, layer, frame, patch, region, bounds.origin(), "AI exact indexed pixels");
  }
  void brushStroke(Document* document, const Json& params) {
    auto sprite = document->sprite();
    auto layer = sprite->pixelFormat() == IMAGE_INDEXED ? indexedLayer(document, params) : paintLayer(document, params);
    int frame = integer(params, "frame", 0, sprite->lastFrame());
    auto selection = paintSelection(document, params);
    require(params.contains("color") != params.contains("index"), "INVALID_PARAMS", "Supply exactly one RGBA color or palette index.");
    require(sprite->pixelFormat() == IMAGE_INDEXED ? params.contains("index") : params.contains("color"), "UNSUPPORTED_COLOR_MODE", "Indexed sprites require an exact index; RGBA sprites require color. No conversion is performed.");
    auto paint = sprite->pixelFormat() == IMAGE_INDEXED ? indexedColor(sprite, frame, params) : color(params);
    require(params.contains("brush") && params["brush"].is_object(), "INVALID_PARAMS", "Supply a bitmap brush.");
    const auto& brush = params["brush"];
    int width = integer(brush, "width", 1, 32), height = integer(brush, "height", 1, 32);
    auto bits = text(brush, "bits", 1024);
    require(bits.size() == size_t(width * height) && bits.find_first_not_of("01") == std::string::npos, "INVALID_PARAMS", "Brush bits must be exactly width*height binary digits, row-major.");
    int ax = brush.contains("anchorX") ? integer(brush, "anchorX", 0, width - 1) : width / 2;
    int ay = brush.contains("anchorY") ? integer(brush, "anchorY", 0, height - 1) : height / 2;
    std::vector<gfx::Point> offsets;
    for (int y = 0; y < height; ++y) for (int x = 0; x < width; ++x) if (bits[y * width + x] == '1') offsets.emplace_back(x - ax, y - ay);
    require(!offsets.empty(), "INVALID_PARAMS", "Brush must contain at least one set bit.");
    require(params.contains("points") && params["points"].is_array() && !params["points"].empty() && params["points"].size() <= 1024, "INVALID_PARAMS", "Supply 1 to 1024 stroke points.");
    bool clip = params.contains("clipToCanvas") ? boolean(params, "clipToCanvas") : false;
    std::vector<gfx::Point> points;
    for (const auto& point : params["points"]) {
      int x = integer(point, "x", 0, sprite->width() - 1), y = integer(point, "y", 0, sprite->height() - 1);
      require(clip || sprite->bounds().contains(gfx::Rect(x - ax, y - ay, width, height)), "OUTSIDE_CANVAS", "Brush footprint would clip. Explicitly set clipToCanvas:true.");
      points.emplace_back(x, y);
    }
    ImageRef centers(Image::create(IMAGE_BITMAP, sprite->width(), sprite->height())); centers->clear(0);
    centers->putPixel(points.front().x, points.front().y, 1);
    for (size_t i = 1; i < points.size(); ++i) doc::draw_line(centers.get(), points[i - 1].x, points[i - 1].y, points[i].x, points[i].y, 1);
    size_t count = 0;
    for (int y = 0; y < sprite->height(); ++y) for (int x = 0; x < sprite->width(); ++x) count += centers->getPixel(x, y) != 0;
    require(count * offsets.size() <= 8 * 1024 * 1024, "LIMIT_EXCEEDED", "Brush stroke exceeds 8,388,608 stamp-pixel visits.");
    ImageRef painted(Image::create(IMAGE_BITMAP, sprite->width(), sprite->height())); painted->clear(0);
    for (int y = 0; y < sprite->height(); ++y) for (int x = 0; x < sprite->width(); ++x) if (centers->getPixel(x, y))
      for (const auto& offset : offsets) if (sprite->bounds().contains(x + offset.x, y + offset.y) && (!selection || selection->containsPoint(x + offset.x, y + offset.y))) painted->putPixel(x + offset.x, y + offset.y, 1);
    ImageRef patch(Image::create(sprite->pixelFormat(), sprite->width(), sprite->height()));
    auto clear = sprite->pixelFormat() == IMAGE_INDEXED ? sprite->transparentColor() : color_t(0);
    patch->setMaskColor(sprite->transparentColor()); patch->clear(clear);
    auto cel = layer->cel(frame);
    gfx::Region region;
    for (int y = 0; y < sprite->height(); ++y) {
      int start = -1;
      for (int x = 0; x <= sprite->width(); ++x) {
        bool changed = false;
        if (x < sprite->width() && painted->getPixel(x, y)) {
          auto old = cel && cel->bounds().contains(x, y) ? cel->image()->getPixel(x - cel->x(), y - cel->y()) : clear;
          changed = old != paint;
          if (changed) patch->putPixel(x, y, paint);
        }
        if (changed && start < 0) start = x;
        if (!changed && start >= 0) { region |= gfx::Region(gfx::Rect(start, y, x - start, 1)); start = -1; }
      }
    }
    applyPatch(document, layer, frame, patch, region, gfx::Point(0, 0), "AI bitmap brush stroke");
  }
  void draw(Document* document, const Json& params, const std::string& method) {
    auto sprite = document->sprite();
    auto target = paintLayer(document, params);
    auto frame = integer(params, "frame", 0, sprite->totalFrames() - 1);
    auto selection = paintSelection(document, params);
    auto paint = color(params);
    auto label = params.contains("label") ? text(params, "label", 120) : "AI drawing";
    ImageRef mask(Image::create(IMAGE_BITMAP, sprite->width(), sprite->height()));
    mask->clear(0);
    if (method == "draw_shape") {
      auto shape = text(params, "shape", 16);
      require(shape == "line" || shape == "rectangle" || shape == "ellipse", "INVALID_PARAMS", "shape must be line, rectangle, or ellipse.");
      int x1 = integer(params, "x1", 0, sprite->width() - 1), y1 = integer(params, "y1", 0, sprite->height() - 1);
      int x2 = integer(params, "x2", 0, sprite->width() - 1), y2 = integer(params, "y2", 0, sprite->height() - 1);
      bool filled = params.contains("filled") ? boolean(params, "filled") : false;
      require(shape != "line" || !filled, "INVALID_PARAMS", "A line cannot be filled.");
      if (shape == "line") doc::draw_line(mask.get(), x1, y1, x2, y2, 1);
      else {
        if (x1 > x2) std::swap(x1, x2);
        if (y1 > y2) std::swap(y1, y2);
        if (shape == "rectangle") {
          if (filled) doc::fill_rect(mask.get(), x1, y1, x2, y2, 1);
          else doc::draw_rect(mask.get(), x1, y1, x2, y2, 1);
        } else {
          if (filled) doc::fill_ellipse(mask.get(), x1, y1, x2, y2, 1);
          else doc::draw_ellipse(mask.get(), x1, y1, x2, y2, 1);
        }
      }
    } else if (method == "draw_stroke") {
      require(params.contains("points") && params["points"].is_array() && !params["points"].empty() && params["points"].size() <= 1024,
              "INVALID_PARAMS", "A stroke requires 1 to 1024 points.");
      std::vector<gfx::Point> points;
      for (const auto& point : params["points"])
        points.emplace_back(integer(point, "x", 0, sprite->width() - 1), integer(point, "y", 0, sprite->height() - 1));
      // Connected, one-pixel native lines. Brush engines/pressure are deferred.
      doc::put_pixel(mask.get(), points.front().x, points.front().y, 1);
      for (size_t i = 1; i < points.size(); ++i)
        doc::draw_line(mask.get(), points[i - 1].x, points[i - 1].y, points[i].x, points[i].y, 1);
    } else {
      int x = integer(params, "x", 0, sprite->width() - 1), y = integer(params, "y", 0, sprite->height() - 1);
      int tolerance = params.contains("tolerance") ? integer(params, "tolerance", 0, 255) : 0;
      bool contiguous = params.contains("contiguous") ? boolean(params, "contiguous") : true;
      if (selection && !selection->containsPoint(x, y)) return;
      // Flood against a full canvas of this cel ONLY, not the visible composite.
      // Pixel sampling remains stable while the callback writes the mask.
      ImageRef source(Image::create(IMAGE_RGB, sprite->width(), sprite->height()));
      source->clear(0);
      if (auto cel = target->cel(frame)) doc::copy_image(source.get(), cel->image(), cel->x(), cel->y());
      doc::algorithm::floodfill(source.get(), selection, x, y, sprite->bounds(), tolerance, contiguous, mask.get(),
        [](int x1, int y, int x2, void* data) { doc::draw_hline(static_cast<Image*>(data), x1, y, x2, 1); });
    }
    ImageRef patch(Image::create(IMAGE_RGB, sprite->width(), sprite->height()));
    patch->clear(0);
    gfx::Region region;
    auto cel = target->cel(frame);
    // Convert the mask to changed scanline spans. No-op draws do not consume
    // undo history, and unselected pixels in an existing cel stay untouched.
    for (int y = 0; y < sprite->height(); ++y) {
      int start = -1;
      for (int x = 0; x <= sprite->width(); ++x) {
        bool changed = false;
        if (x < sprite->width() && mask->getPixel(x, y) && (!selection || selection->containsPoint(x, y))) {
          auto old = cel ? doc::get_pixel(cel->image(), x - cel->x(), y - cel->y()) : 0;
          // get_pixel returns -1 outside an image: outside a cropped cel is transparent.
          if (!cel || !cel->bounds().contains(x, y)) old = 0;
          changed = old != paint;
          if (changed) patch->putPixel(x, y, paint);
        }
        if (changed && start < 0) start = x;
        if (!changed && start >= 0) { region |= gfx::Region(gfx::Rect(start, y, x - start, 1)); start = -1; }
      }
    }
    applyPatch(document, target, frame, patch, region, gfx::Point(0, 0), label);
  }
  void selectionPixels(Document* document, const Json& params, bool translating) {
    auto sprite = document->sprite();
    auto target = paintLayer(document, params);
    int frame = integer(params, "frame", 0, sprite->lastFrame());
    auto mask = visibleSelection(document);
    auto cel = target->cel(frame);
    ImageRef patch(Image::create(IMAGE_RGB, sprite->width(), sprite->height()));
    patch->clear(0);
    auto sample = [&](int x, int y) { return cel && cel->bounds().contains(x, y) ? cel->image()->getPixel(x - cel->x(), y - cel->y()) : color_t(0); };
    Mask moved;
    if (translating) {
      int dx = integer(params, "dx", -1023, 1023), dy = integer(params, "dy", -1023, 1023);
      bool copy = params.contains("copy") ? boolean(params, "copy") : false;
      require(sprite->bounds().contains(mask->bounds()), "SELECTION_OUTSIDE_CANVAS", "Selection must lie entirely inside the canvas for pixel translation.");
      auto destination = mask->bounds(); destination.offset(dx, dy);
      require(sprite->bounds().contains(destination), "OUTSIDE_CANVAS", "Translated selection would leave the canvas. Clipping is refused.");
      if (dx == 0 && dy == 0) return;
      // Snapshot BEFORE clearing or writing, so overlaps never read edited data.
      for (int y = 0; y < sprite->height(); ++y)
        for (int x = 0; x < sprite->width(); ++x) patch->putPixel(x, y, sample(x, y));
      if (!copy) for (int y = 0; y < sprite->height(); ++y)
        for (int x = 0; x < sprite->width(); ++x) if (mask->containsPoint(x, y)) patch->putPixel(x, y, 0);
      for (int y = 0; y < sprite->height(); ++y)
        for (int x = 0; x < sprite->width(); ++x) if (mask->containsPoint(x, y)) patch->putPixel(x + dx, y + dy, sample(x, y));
      moved.copyFrom(mask); moved.offsetOrigin(dx, dy);
    } else {
      auto paint = color(params);
      for (int y = 0; y < sprite->height(); ++y)
        for (int x = 0; x < sprite->width(); ++x) patch->putPixel(x, y, mask->containsPoint(x, y) ? paint : sample(x, y));
    }
    gfx::Region region;
    for (int y = 0; y < sprite->height(); ++y) {
      int start = -1;
      for (int x = 0; x <= sprite->width(); ++x) {
        bool changed = x < sprite->width() && patch->getPixel(x, y) != sample(x, y);
        if (changed && start < 0) start = x;
        if (!changed && start >= 0) { region |= gfx::Region(gfx::Rect(start, y, x - start, 1)); start = -1; }
      }
    }
    applyPatch(document, target, frame, patch, region, gfx::Point(0, 0), translating ? "AI translate selected pixels" : "AI fill selected pixels", translating ? &moved : nullptr);
  }
  Json transformSelection(Document* document, const Json& params) {
    auto sprite = document->sprite();
    auto frames = uniqueFrames(sprite, params);
    auto operation = transformOperation(params);
    auto mask = visibleSelection(document);
    auto bounds = mask->bounds();
    require(sprite->bounds().contains(bounds), "SELECTION_OUTSIDE_CANVAS", "Selection must lie entirely inside the canvas.");
    bool quarter = operation == "rotate_cw" || operation == "rotate_ccw";
    gfx::Rect destination(bounds.x, bounds.y, quarter ? bounds.h : bounds.w, quarter ? bounds.w : bounds.h);
    require(sprite->bounds().contains(destination), "OUTSIDE_CANVAS", "Transformed selection would leave the canvas. Clipping is refused.");
    auto area = bounds | destination;
    Layer* layer = nullptr;
    size_t predicted = spriteBytes(sprite);
    // Validate every target and aggregate worst-case crop growth BEFORE allocating.
    for (int frame : frames) {
      auto entry = params; entry["frame"] = frame;
      layer = paintLayer(document, entry);
      auto cel = layer->cel(frame);
      if (cel) {
        auto grown = cel->bounds() | area;
        predicted += size_t(grown.w) * grown.h * 4 - imageBytes(cel->image());
      } else predicted += size_t(area.w) * area.h * 4;
    }
    require(predicted <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Selected transforms would exceed the sprite's 32 MiB working limit.");
    require(size_t(area.w) * area.h * 4 * frames.size() <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Selected-transform scratch exceeds 32 MiB.");
    Mask transformed;
    transformed.replace(destination); transformed.bitmap()->clear(0);
    for (int y = 0; y < bounds.h; ++y) for (int x = 0; x < bounds.w; ++x) if (mask->containsPoint(x + bounds.x, y + bounds.y)) {
      auto p = transformedPoint(x, y, bounds.w, bounds.h, operation);
      transformed.bitmap()->putPixel(p.x, p.y, 1);
    }
    transformed.shrink();
    struct Patch { int frame; ImageRef image; gfx::Region region; };
    std::vector<Patch> patches;
    int changedFrames = 0;
    for (int frame : frames) {
      auto cel = layer->cel(frame);
      auto sample = [&](int x, int y) { return cel && cel->bounds().contains(x, y) ? cel->image()->getPixel(x - cel->x(), y - cel->y()) : color_t(0); };
      Patch patch{frame, ImageRef(Image::create(IMAGE_RGB, area.w, area.h)), {}};
      for (int y = 0; y < area.h; ++y) for (int x = 0; x < area.w; ++x) patch.image->putPixel(x, y, sample(x + area.x, y + area.y));
      // Clear only original mask bits, then paste samples from the original cel,
      // including transparent pixels. Overlap never reads already-modified data.
      for (int y = 0; y < bounds.h; ++y) for (int x = 0; x < bounds.w; ++x) if (mask->containsPoint(x + bounds.x, y + bounds.y))
        patch.image->putPixel(x + bounds.x - area.x, y + bounds.y - area.y, 0);
      for (int y = 0; y < bounds.h; ++y) for (int x = 0; x < bounds.w; ++x) if (mask->containsPoint(x + bounds.x, y + bounds.y)) {
        auto p = transformedPoint(x, y, bounds.w, bounds.h, operation);
        patch.image->putPixel(p.x + destination.x - area.x, p.y + destination.y - area.y, sample(x + bounds.x, y + bounds.y));
      }
      for (int y = 0; y < area.h; ++y) {
        int start = -1;
        for (int x = 0; x <= area.w; ++x) {
          bool changed = x < area.w && patch.image->getPixel(x, y) != sample(x + area.x, y + area.y);
          if (changed && start < 0) start = x;
          if (!changed && start >= 0) { patch.region |= gfx::Region(gfx::Rect(start, y, x - start, 1)); start = -1; }
        }
      }
      if (!patch.region.isEmpty()) ++changedFrames;
      patches.push_back(std::move(patch));
    }
    bool maskChanged = !sameSelection(document, transformed);
    if (!changedFrames && !maskChanged) return {{"transformedFrames", 0}};
    Transaction transaction(UIContext::instance(), "AI transform selected pixels across frames", changedFrames ? ModifyDocument : DoesntModifyDocument);
    for (auto& patch : patches) if (!patch.region.isEmpty()) {
      if (auto cel = layer->cel(patch.frame)) transaction.execute(new cmd::PatchCel(cel, patch.image.get(), patch.region, gfx::Point(area.x, area.y)));
      else {
        auto created = std::make_shared<Cel>(patch.frame, patch.image);
        created->setPosition(area.x, area.y);
        transaction.execute(new cmd::AddCel(layer, created));
      }
    }
    if (maskChanged) transaction.execute(new cmd::SetMask(document, &transformed));
    finish(transaction, document);
    if (maskChanged) document->generateMaskBoundaries();
    UIContext::instance()->activeEditor()->setLayer(layer);
    UIContext::instance()->activeEditor()->setFrame(frames.front());
    return {{"transformedFrames", changedFrames}, {"frames", frames}, {"operation", operation}};
  }
  Json editLayers(Document* document, const Json& params, const std::string& method) {
    auto sprite = document->sprite();
    Json result = Json::object();
    if (method == "create_layer") {
      require(int(sprite->countLayers()) < 128, "LIMIT_EXCEEDED", "At most 128 layers are supported.");
      auto name = text(params, "name", 120);
      auto type = params.contains("type") ? text(params, "type", 16) : "image";
      require(type == "image" || type == "group", "INVALID_PARAMS", "Layer type must be image or group.");
      Layer* parent = sprite->folder();
      if (params.contains("parentId") && !params["parentId"].is_null()) parent = findLayer(sprite, integer(params, "parentId", 1, INT32_MAX));
      require(parent->isFolder(), "INVALID_PARAMS", "parentId must identify a group.");
      editable(parent);
      auto folder = static_cast<LayerFolder*>(parent);
      auto after = folder->getLastLayer();
      if (params.contains("afterLayerId")) after = params["afterLayerId"].is_null() ? nullptr : findLayer(sprite, integer(params, "afterLayerId", 1, INT32_MAX));
      require(!after || after->parent() == folder, "INVALID_PARAMS", "Insertion reference must be a sibling in the target group.");
      require(after || !folder->getFirstLayer() || !folder->getFirstLayer()->isBackground(), "UNSUPPORTED_LAYER", "Cannot insert below a background layer.");
      std::unique_ptr<Layer> layer(type == "image" ? static_cast<Layer*>(new LayerImage(sprite)) : static_cast<Layer*>(new LayerFolder(sprite)));
      layer->setName(name);
      auto id = layer->id();
      Transaction transaction(UIContext::instance(), "AI create layer");
      transaction.execute(new cmd::AddLayer(folder, layer.get(), after));
      layer.release(); // Now owned by the sprite, or deleted by transaction rollback.
      finish(transaction, document);
      result["createdLayerId"] = id;
    } else {
      auto layer = findLayer(sprite, integer(params, "layerId", 1, INT32_MAX));
      if (method == "update_layer") {
        // Explicit unlocking is allowed, but not edits hidden inside an unlock.
        editable(layer->parent());
        bool hasProperties = params.contains("name") || params.contains("opacity") || params.contains("visible") || params.contains("blendMode");
        require(layer->isEditable() || !hasProperties, "LAYER_LOCKED", "Unlock the layer in a separate request before modifying its properties.");
        require(hasProperties || params.contains("editable"), "INVALID_PARAMS", "Supply at least one layer property.");
        auto name = params.contains("name") ? text(params, "name", 120) : layer->name();
        int opacity = -1;
        int blend = -1;
        if (params.contains("blendMode")) {
          require(layer->isImage() && !layer->isBackground(), "UNSUPPORTED_LAYER", "Blend modes require a transparent image layer.");
          static const std::vector<std::string> names = {"normal", "multiply", "screen", "overlay", "darken", "lighten", "color_dodge", "color_burn", "hard_light", "soft_light", "difference", "exclusion", "hue", "saturation", "color", "luminosity"};
          auto value = text(params, "blendMode", 24);
          auto found = std::find(names.begin(), names.end(), value);
          require(found != names.end(), "INVALID_PARAMS", "Unknown native blend mode.");
          blend = std::distance(names.begin(), found);
        }
        if (params.contains("opacity")) {
          require(layer->isImage() && !layer->isBackground(), "UNSUPPORTED_LAYER", "Opacity changes require a transparent image layer.");
          opacity = integer(params, "opacity", 0, 255);
        }
        auto flags = int(layer->flags());
        for (auto entry : {std::make_pair("visible", LayerFlags::Visible), std::make_pair("editable", LayerFlags::Editable)})
          if (params.contains(entry.first)) flags = boolean(params, entry.first) ? flags | int(entry.second) : flags & ~int(entry.second);
        bool changed = name != layer->name() || flags != int(layer->flags()) ||
          (opacity >= 0 && opacity != static_cast<LayerImage*>(layer)->opacity()) ||
          (blend >= 0 && blend != int(static_cast<LayerImage*>(layer)->blendMode()));
        if (changed) {
          Transaction transaction(UIContext::instance(), "AI update layer");
          if (name != layer->name()) transaction.execute(new cmd::SetLayerName(layer, name));
          if (flags != int(layer->flags())) transaction.execute(new cmd::SetLayerFlags(layer, LayerFlags(flags)));
          if (opacity >= 0 && opacity != static_cast<LayerImage*>(layer)->opacity()) transaction.execute(new cmd::SetLayerOpacity(static_cast<LayerImage*>(layer), opacity));
          if (blend >= 0 && blend != int(static_cast<LayerImage*>(layer)->blendMode())) transaction.execute(new cmd::SetLayerBlendMode(static_cast<LayerImage*>(layer), BlendMode(blend)));
          finish(transaction, document);
        }
      } else if (method == "move_layer") {
        editable(layer);
        require(!layer->isBackground(), "UNSUPPORTED_LAYER", "Cannot restack a background layer.");
        require(params.contains("afterLayerId"), "INVALID_PARAMS", "Supply afterLayerId, or null for the bottom of this group.");
        auto after = params["afterLayerId"].is_null() ? nullptr : findLayer(sprite, integer(params, "afterLayerId", 1, INT32_MAX));
        require(after != layer && (!after || after->parent() == layer->parent()), "INVALID_PARAMS", "Move reference must be a different sibling in the same group.");
        require(after || !layer->parent()->getFirstLayer()->isBackground(), "UNSUPPORTED_LAYER", "Cannot move below a background layer.");
        if (layer->getPrevious() != after) {
          Transaction transaction(UIContext::instance(), "AI move layer");
          transaction.execute(new cmd::MoveLayer(layer, after));
          finish(transaction, document);
        }
      } else {
        editable(layer);
        if (layer->isFolder() && static_cast<LayerFolder*>(layer)->getLayersCount() > 0)
          require(params.contains("recursive") && boolean(params, "recursive"), "GROUP_NOT_EMPTY", "Nonempty group removal requires recursive:true.");
        int survivingImages = 0;
        for (auto candidate : sprite->layers()) {
          bool inside = false;
          for (auto ancestor = candidate; ancestor; ancestor = ancestor->parent()) if (ancestor == layer) inside = true;
          if (inside) { editable(candidate); require(!candidate->isBackground(), "UNSUPPORTED_LAYER", "Cannot remove a background layer."); }
          else if (candidate->isImage()) ++survivingImages;
        }
        require(survivingImages > 0, "LAST_LAYER", "At least one image layer must remain.");
        Transaction transaction(UIContext::instance(), "AI remove layer");
        transaction.execute(new cmd::RemoveLayer(layer));
        finish(transaction, document);
      }
    }
    return result;
  }
  Json editFrames(Document* document, const Json& params, const std::string& method) {
    auto sprite = document->sprite();
    Json result = Json::object();
    if (method == "set_frame_duration") {
      int frame = integer(params, "frame", 0, sprite->totalFrames() - 1);
      int duration = integer(params, "durationMs", 1, 65535);
      if (sprite->frameDuration(frame) != duration) {
        Transaction transaction(UIContext::instance(), "AI frame duration");
        transaction.execute(new cmd::SetFrameDuration(sprite, frame, duration));
        finish(transaction, document);
      }
      UIContext::instance()->activeEditor()->setFrame(frame);
      return result;
    }
    require(sprite->getPalettes().size() == 1, "UNSUPPORTED_PALETTES", "Frame insertion/removal with per-frame palettes is not supported yet.");
    for (auto layer : sprite->layers()) editable(layer);
    if (method == "add_frame") {
      require(sprite->totalFrames() < 256, "LIMIT_EXCEEDED", "At most 256 frames are supported.");
      int index = integer(params, "index", 0, sprite->totalFrames());
      int source = params.contains("copyFrom") ? integer(params, "copyFrom", 0, sprite->totalFrames() - 1) : -1;
      int duration = params.contains("durationMs") ? integer(params, "durationMs", 1, 65535) : source >= 0 ? sprite->frameDuration(source) : 100;
      Transaction transaction(UIContext::instance(), source >= 0 ? "AI duplicate frame" : "AI blank frame");
      // Reuse the existing API for its undoable frame-tag range adjustments.
      document->getApi(transaction).addEmptyFrame(sprite, index);
      transaction.execute(new cmd::SetFrameDuration(sprite, index, duration));
      if (source >= 0) {
        if (source >= index) ++source;
        for (auto layer : sprite->layers()) if (layer->isImage())
          transaction.execute(new cmd::CopyCel(static_cast<LayerImage*>(layer), source, static_cast<LayerImage*>(layer), index, false));
      }
      finish(transaction, document);
      UIContext::instance()->activeEditor()->setFrame(index);
      result["insertedFrame"] = index;
    } else {
      require(sprite->totalFrames() > 1, "LAST_FRAME", "At least one frame must remain.");
      int frame = integer(params, "frame", 0, sprite->totalFrames() - 1);
      Transaction transaction(UIContext::instance(), "AI remove frame");
      document->getApi(transaction).removeFrame(sprite, frame);
      finish(transaction, document);
      UIContext::instance()->activeEditor()->setFrame(std::min(frame, sprite->lastFrame()));
    }
    return result;
  }
  void save(Document* document, const Json& params) {
    auto path = filePath(params, true);
    require(path.extension() == ".ase" || path.extension() == ".aseprite", "INVALID_PATH", "Native saving requires .ase or .aseprite.");
    bool overwrite = params.value("overwrite", false);
    require(overwrite || !fs::exists(path), "FILE_EXISTS", "Destination exists; explicitly allow overwrite or choose another filename.");
    // Encode to a unique sibling first. Failed saves never corrupt the target.
    std::string pattern = (path.parent_path() / ".libresprite-save-XXXXXX.ase").string();
    std::vector<char> temporary(pattern.begin(), pattern.end()); temporary.push_back('\0');
    int fd = mkstemps(temporary.data(), 4);
    require(fd >= 0, "IO_ERROR", "Cannot create temporary save file."); close(fd);
    try {
      std::unique_ptr<FileOp> operation(FileOp::createSaveDocumentOperation(nullptr, document, temporary.data(), ""));
      require(operation && !operation->hasError(), "SAVE_FAILED", operation ? operation->error() : "Cannot create native save operation.");
      operation->operate(); operation->done();
      require(!operation->hasError(), "SAVE_FAILED", operation->error());
      if (overwrite) fs::rename(temporary.data(), path);
      else {
        require(link(temporary.data(), path.c_str()) == 0, "FILE_EXISTS", "Destination appeared during saving, or could not be published.");
        unlink(temporary.data());
      }
    } catch (...) { unlink(temporary.data()); throw; }
    document->setFilename(path.string()); document->markAsSaved();
    App::instance()->updateDisplayTitleBar();
  }
  Json dispatch(const std::string& method, const Json& params) {
    auto ctx = UIContext::instance();
    static const std::vector<std::string> methods = {"status", "set_paused", "list_documents", "inspect", "render", "create", "open", "set_pixels", "undo", "redo", "save", "create_layer", "update_layer", "move_layer", "remove_layer", "add_frame", "remove_frame", "set_frame_duration", "draw_shape", "draw_stroke", "flood_fill", "list_assets", "preview_asset", "contact_sheet", "render_onion_skin", "export_png", "export_sprite_sheet", "set_palette", "remove_palette", "create_tag", "update_tag", "remove_tag", "export_animation", "update_cel", "transform_cel", "unlink_cel", "set_selection", "modify_selection", "render_selection", "fill_selection", "translate_selection", "activate_document", "set_active_site", "close_document", "copy_cel", "duplicate_frames", "reorder_frames", "edit_cels", "set_frame_durations", "transform_selection", "resize_canvas", "crop_canvas", "duplicate_layer", "reparent_layer", "draw_brush_stroke", "set_indexed_pixels", "set_polygon_selection", "set_bitmap_selection"};
    require(std::find(methods.begin(), methods.end(), method) != methods.end(), "METHOD_NOT_FOUND", "Unknown bridge method.");
    if (method == "status") return {{"protocolVersion", 1}, {"bridgeVersion", "0.9.0"}, {"methods", methods}, {"sessionId", m_session}, {"connected", m_client >= 0}, {"paused", m_paused}, {"pausedByUser", m_pausedByUser}, {"controlText", m_control ? m_control->text() : ""}, {"assetRoot", m_root.string()}, {"pid", getpid()}};
    require(text(params, "sessionId", 128) == m_session, "SESSION_MISMATCH", "This request belongs to a different editor process.");
    if (method == "set_paused") {
      require(params.contains("paused") && params["paused"].is_boolean(), "INVALID_PARAMS", "paused must be boolean.");
      bool paused = params["paused"].get<bool>();
      require(paused || !m_pausedByUser, "USER_PAUSED", "Agent edits were paused in the editor. Click Resume in the editor to release the local pause.");
      if (!paused) uiIdle();
      m_paused = paused;
      updateControl();
      return {{"paused", m_paused}, {"pausedByUser", m_pausedByUser}, {"sessionId", m_session}};
    }
    uiIdle();
    if (method == "list_assets") return listAssets(params);
    if (method == "preview_asset") return previewAsset(params);
    if (method == "list_documents") {
      Json documents = Json::array();
      for (auto item : ctx->documents()) {
        auto document = static_cast<Document*>(item);
        DocumentReader reader(document, 0);
        documents.push_back(summary(document));
      }
      return {{"documents", documents}, {"activeDocumentId", ctx->activeDocument() ? Json(ctx->activeDocument()->id()) : Json(nullptr)}, {"paused", m_paused}, {"sessionId", m_session}};
    }
    bool read = method == "inspect" || method == "render" || method == "contact_sheet" || method == "render_onion_skin" || method == "render_selection";
    require(read || !m_paused, "PAUSED", "Bridge is paused. Explicitly resume before modifying documents.");
    if (method == "create") {
      require(ctx->documents().size() < 32, "LIMIT_EXCEEDED", "At most 32 documents may be opened through this bridge.");
      int width = integer(params, "width", 1, 1024), height = integer(params, "height", 1, 1024);
      auto mode = params.contains("colorMode") ? text(params, "colorMode", 16) : "rgba";
      require(mode == "rgba" || mode == "indexed", "INVALID_PARAMS", "New sprites support rgba or indexed colorMode.");
      std::unique_ptr<Sprite> sprite(Sprite::createBasicSprite(mode == "indexed" ? IMAGE_INDEXED : IMAGE_RGB, width, height, 256));
      std::unique_ptr<Document> document(new Document(sprite.get())); sprite.release();
      document->setFilename(text(params, "name", 120));
      document->setContext(ctx);
      auto result = inspect(document.get()); document.release();
      return result;
    }
    if (method == "open") {
      require(ctx->documents().size() < 32, "LIMIT_EXCEEDED", "At most 32 documents may be opened through this bridge.");
      auto path = filePath(params, false);
      auto document = loadAsset(path);
      // Validate working limits before attaching a document to the GUI.
      inspect(document.get());
      document->setContext(ctx); auto result = inspect(document.get()); document.release();
      return result;
    }
    auto document = findDocument(params);
    if (read) {
      DocumentReader reader(document, 0);
      if (method == "inspect") return inspect(document);
      if (method == "contact_sheet") return contactSheet(document, params);
      if (method == "render_onion_skin") return renderOnionSkin(document, params);
      if (method == "render_selection") return renderSelection(document, params);
      return renderFrame(document, params);
    }
    if (method == "activate_document") return activateDocument(document, params);
    require(ctx->activeDocument() == document, "INACTIVE_DOCUMENT", "Target must be the active GUI document. Refusing to switch silently.");
    if (method == "set_active_site") return focusSite(document, params);
    if (method == "close_document") return closeDocument(document, params);
    if (method == "export_png" || method == "export_sprite_sheet" || method == "export_animation") {
      DocumentReader reader(document, 0);
      checkRevision(document, params);
      return method == "export_animation" ? exportAnimation(document, params) : exportPng(document, params, method == "export_sprite_sheet");
    }
    // Check and mutate under the same lock, on the same UI tick.
    ContextWriter writer(ctx, 0);
    checkRevision(document, params);
    documentViewsIdle(document);
    SelectionGuard selection(document);
    Json extra = Json::object();
    if (method == "set_pixels") {
      // setPixels owns its transaction but reuses this writer lock.
      setPixels(document, params);
    } else if (method == "resize_canvas" || method == "crop_canvas") {
      extra = canvas(document, params, method == "crop_canvas");
    } else if (method == "duplicate_layer") {
      extra = duplicateLayer(document, params);
    } else if (method == "reparent_layer") {
      extra = reparentLayer(document, params);
    } else if (method == "draw_brush_stroke") {
      brushStroke(document, params);
    } else if (method == "set_indexed_pixels") {
      indexedPixels(document, params);
    } else if (method == "set_polygon_selection" || method == "set_bitmap_selection") {
      advancedSelection(document, params, method == "set_polygon_selection");
    } else if (method == "draw_shape" || method == "draw_stroke" || method == "flood_fill") {
      draw(document, params, method);
    } else if (method == "create_layer" || method == "update_layer" || method == "move_layer" || method == "remove_layer") {
      extra = editLayers(document, params, method);
    } else if (method == "add_frame" || method == "remove_frame" || method == "set_frame_duration") {
      extra = editFrames(document, params, method);
    } else if (method == "set_palette" || method == "remove_palette") {
      editPalette(document, params, method == "remove_palette");
    } else if (method == "create_tag" || method == "update_tag" || method == "remove_tag") {
      extra = editTags(document, params, method);
    } else if (method == "update_cel" || method == "transform_cel" || method == "unlink_cel") {
      editCel(document, params, method);
    } else if (method == "copy_cel") {
      extra = copyCel(document, params);
    } else if (method == "duplicate_frames") {
      extra = duplicateFrames(document, params);
    } else if (method == "reorder_frames") {
      extra = reorderFrames(document, params);
    } else if (method == "edit_cels") {
      extra = editCels(document, params);
    } else if (method == "set_frame_durations") {
      extra = frameDurations(document, params);
    } else if (method == "transform_selection") {
      extra = transformSelection(document, params);
    } else if (method == "set_selection" || method == "modify_selection") {
      editSelection(document, params, method == "modify_selection");
    } else if (method == "fill_selection" || method == "translate_selection") {
      selectionPixels(document, params, method == "translate_selection");
    } else if (method == "undo" || method == "redo") {
      auto history = document->undoHistory();
      require(method == "undo" ? history->canUndo() : history->canRedo(), "NO_HISTORY", "No matching undo/redo state.");
      auto position = method == "undo" ? history->nextUndoSpritePosition() : history->nextRedoSpritePosition();
      if (method == "undo") history->undo(); else history->redo();
      auto sprite = document->sprite();
      if (position.layerIndex() >= LayerIndex(0) && position.layerIndex() < sprite->countLayers())
        ctx->activeEditor()->setLayer(sprite->indexToLayer(position.layerIndex()));
      ctx->activeEditor()->setFrame(std::min(position.frame(), sprite->lastFrame()));
      document->generateMaskBoundaries(); document->notifyGeneralUpdate();
    } else if (method == "save") save(document, params);
    else throw BridgeError("METHOD_NOT_FOUND", "Unknown bridge method.");
    selection.committed = true;
    // Match native New Layer/New Frame behavior, including the user's existing
    // auto-show preference. Visible timeline rows are safe for group layers.
    if (method == "create_layer" || method == "add_frame" || method == "duplicate_frames" || method == "duplicate_layer" || method == "reparent_layer") App::instance()->mainWindow()->popTimeline();
    if (method == "set_palette" || method == "remove_palette" || method == "copy_cel" || method == "undo" || method == "redo") {
      set_current_palette(document->sprite()->palette(ctx->activeEditor()->frame()), false);
      ui::Manager::getDefault()->invalidate();
    }
    update_screen_for_document(document);
    auto result = inspect(document);
    result.update(extra);
    return result;
  }
  std::string handle(const std::string& line) {
    Json id = nullptr;
    std::string requestKey, idKey;
    try {
      auto request = Json::parse(line);
      require(request.is_object() && request.value("jsonrpc", "") == "2.0", "INVALID_REQUEST", "Expected JSON-RPC 2.0 request.");
      idKey = text(request, "id", 128); id = idKey;
      auto method = text(request, "method", 64);
      auto params = request.value("params", Json::object());
      require(params.is_object(), "INVALID_PARAMS", "params must be an object.");
      requestKey = request.dump();
      for (const auto& cached : m_cache) if (cached.id == idKey) {
        require(cached.request == requestKey, "REQUEST_ID_REUSED", "Request ID was reused with different contents.");
        return cached.response;
      }
      Json result = dispatch(method, params);
      auto response = Json({{"jsonrpc", "2.0"}, {"id", id}, {"result", result}}).dump();
      require(response.size() <= MaxResponse, "LIMIT_EXCEEDED", "Response too large.");
      // Successful requests, including mutations, are replay-safe across a
      // reconnect while retained. Evicted/unknown IDs must not be auto-retried.
      m_cache.push_back({idKey, requestKey, response});
      m_cacheBytes += requestKey.size() + response.size();
      while (m_cache.size() > 128 || m_cacheBytes > 16 * 1024 * 1024) {
        m_cacheBytes -= m_cache.front().request.size() + m_cache.front().response.size(); m_cache.pop_front();
      }
      return response;
    } catch (const BridgeError& error) {
      int code = error.code == "INVALID_REQUEST" ? -32600 : error.code == "INVALID_PARAMS" ? -32602 : error.code == "METHOD_NOT_FOUND" ? -32601 : -32000;
      return Json({{"jsonrpc", "2.0"}, {"id", id}, {"error", {{"code", code}, {"message", error.what()}, {"data", {{"code", error.code}}}}}}).dump();
    } catch (const LockedDocumentException& error) {
      return Json({{"jsonrpc", "2.0"}, {"id", id}, {"error", {{"code", -32000}, {"message", error.what()}, {"data", {{"code", "BUSY"}}}}}}).dump();
    } catch (const Json::parse_error& error) {
      return Json({{"jsonrpc", "2.0"}, {"id", id}, {"error", {{"code", -32700}, {"message", error.what()}, {"data", {{"code", "PARSE_ERROR"}}}}}}).dump();
    } catch (const Json::exception& error) {
      return Json({{"jsonrpc", "2.0"}, {"id", id}, {"error", {{"code", -32602}, {"message", error.what()}, {"data", {{"code", "INVALID_PARAMS"}}}}}}).dump();
    } catch (const fs::filesystem_error& error) {
      return Json({{"jsonrpc", "2.0"}, {"id", id}, {"error", {{"code", -32000}, {"message", error.what()}, {"data", {{"code", "IO_ERROR"}}}}}}).dump();
    } catch (const std::exception& error) {
      return Json({{"jsonrpc", "2.0"}, {"id", id}, {"error", {{"code", -32603}, {"message", error.what()}, {"data", {{"code", "INTERNAL_ERROR"}}}}}}).dump();
    }
  }
};

AutomationBridge::AutomationBridge(const std::string& socketPath, const std::string& root)
  : m_impl(new Impl(socketPath, root)) {}
AutomationBridge::~AutomationBridge() = default;
}
#else
#include <stdexcept>
namespace app {
class AutomationBridge::Impl {};
AutomationBridge::AutomationBridge(const std::string&, const std::string&) {
  throw std::runtime_error("The automation bridge currently supports macOS and Linux only.");
}
AutomationBridge::~AutomationBridge() = default;
}
#endif
