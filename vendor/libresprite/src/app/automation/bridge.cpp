// LibreSprite AI bridge. Distributed under GNU GPL version 2.
#include "app/automation/bridge.h"

#if defined(__APPLE__) || defined(__linux__)
#include "app/app.h"
#include "app/cmd/add_cel.h"
#include "app/cmd/add_layer.h"
#include "app/cmd/copy_cel.h"
#include "app/cmd/move_layer.h"
#include "app/cmd/patch_cel.h"
#include "app/cmd/remove_layer.h"
#include "app/cmd/set_frame_duration.h"
#include "app/cmd/set_layer_flags.h"
#include "app/cmd/set_layer_name.h"
#include "app/cmd/set_layer_opacity.h"
#include "app/context_access.h"
#include "app/document_api.h"
#include "app/document_undo.h"
#include "app/file/file.h"
#include "app/modules/editors.h"
#include "app/modules/gui.h"
#include "app/transaction.h"
#include "app/ui/editor/editor.h"
#include "app/ui/editor/standby_state.h"
#include "app/ui/main_window.h"
#include "app/ui_context.h"
#include "base/base64.h"
#include "base/sha1_rfc3174.h"
#include "doc/cel.h"
#include "doc/algorithm/floodfill.h"
#include "doc/documents.h"
#include "doc/frame_tag.h"
#include "doc/image.h"
#include "doc/layer.h"
#include "doc/layers_range.h"
#include "doc/palette.h"
#include "doc/primitives.h"
#include "doc/sprite.h"
#include "render/render.h"
#include "she/surface.h"
#include "she/system.h"
#include "ui/manager.h"
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
  explicit SelectionGuard(Document* document) : m_document(document) {
    auto editor = UIContext::instance()->activeEditor();
    m_layerId = editor->layer() ? editor->layer()->id() : 0;
    m_frame = editor->frame();
  }
  ~SelectionGuard() {
    if (committed) return;
    try {
      auto editor = UIContext::instance()->activeEditor();
      for (auto layer : m_document->sprite()->layers()) if (layer->id() == m_layerId) editor->setLayer(layer);
      editor->setFrame(std::min(m_frame, m_document->sprite()->lastFrame()));
      m_document->notifyGeneralUpdate();
    } catch (...) { /* Preserve the original operation error. */ }
  }
  bool committed = false;
private:
  Document* m_document;
  ObjectId m_layerId;
  frame_t m_frame;
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
          {"modified", document->isModified()}};
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
      m_timer.Tick.connect([this] { tick(); });
      m_timer.start();
    } catch (...) {
      close(m_listener);
      if (m_bound) unlink(m_path.c_str());
      throw;
    }
  }
  ~Impl() {
    m_timer.stop();
    disconnect();
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
  bool m_bound = false, m_paused = true;
  size_t m_sent = 0, m_cacheBytes = 0;
  Clock::time_point m_progress = Clock::now();
  std::deque<Cached> m_cache;
  std::map<ObjectId, Revision> m_revisions;

  void disconnect() {
    if (m_client >= 0) close(m_client);
    m_client = -1;
    m_input.clear(); m_output.clear(); m_sent = 0;
    // Disconnect is a safety boundary: edits require explicit resume.
    m_paused = true;
  }
  void tick() noexcept {
    try {
      if (m_client < 0) {
        int fd = accept(m_listener, nullptr, nullptr);
        if (fd < 0) return;
        if (!sameUser(fd)) { close(fd); return; }
        try { nonblocking(fd); } catch (...) { close(fd); throw; }
        m_client = fd; m_progress = Clock::now();
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
      if (layer->isImage()) {
        auto imageLayer = static_cast<LayerImage*>(layer);
        item["opacity"] = imageLayer->opacity(); item["blendMode"] = int(imageLayer->blendMode());
        item["cels"] = Json::array();
        for (auto it = imageLayer->getCelBegin(); it != imageLayer->getCelEnd(); ++it) {
          auto cel = *it;
          item["cels"].push_back({{"frame", cel->frame()}, {"x", cel->x()}, {"y", cel->y()}, {"opacity", cel->opacity()},
                                 {"width", cel->image()->width()}, {"height", cel->image()->height()},
                                 {"imageId", cel->image()->id()}, {"imageVersion", cel->image()->version()}, {"links", cel->links()}});
        }
      }
      result["layers"].push_back(item);
    }
    result["frames"] = Json::array();
    for (frame_t frame = 0; frame < sprite->totalFrames(); ++frame)
      result["frames"].push_back({{"frame", frame}, {"durationMs", sprite->frameDuration(frame)}});
    result["palettes"] = Json::array();
    for (const auto& palette : sprite->getPalettes()) {
      require(palette->size() <= 4096, "LIMIT_EXCEEDED", "Palette is too large.");
      Json entries = Json::array();
      for (int i = 0; i < palette->size(); ++i) entries.push_back(palette->getEntry(i));
      result["palettes"].push_back({{"frame", palette->frame()}, {"rgbaPacked", entries}});
    }
    result["tags"] = Json::array();
    for (auto tag : sprite->frameTags())
      result["tags"].push_back({{"name", tag->name()}, {"from", tag->fromFrame()}, {"to", tag->toFrame()}, {"direction", int(tag->aniDir())}, {"color", tag->color()}});
    result["canUndo"] = document->undoHistory()->canUndo();
    result["canRedo"] = document->undoHistory()->canRedo();
    return result;
  }
  int revision(Document* document, const Json& metadata) {
    // Fingerprint native state AND image bytes: catches ordinary manual edits,
    // undo/redo, palette changes, and script writes that bypass undo commands.
    SHA1Context hash; SHA1Reset(&hash);
    std::string encoded = metadata.dump() + std::to_string(reinterpret_cast<uintptr_t>(document->undoHistory()->currentState()));
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
  void publishPng(const fs::path& path, const std::vector<uint8_t>& bytes, bool overwrite) {
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
        require(count > 0, "IO_ERROR", "Cannot write PNG export.");
        written += size_t(count);
      }
      int closeResult = close(fd); fd = -1;
      require(closeResult == 0, "IO_ERROR", "Cannot finish PNG export.");
      if (overwrite) fs::rename(temporary.data(), path);
      else {
        auto published = link(temporary.data(), path.c_str());
        require(published == 0, errno == EEXIST ? "FILE_EXISTS" : "IO_ERROR", "Could not publish PNG; destination may have appeared during export.");
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
    publishPng(path, bytes, overwrite);
    return result;
  }
  Layer* paintLayer(Document* document, const Json& params) {
    auto sprite = document->sprite();
    require(sprite->pixelFormat() == IMAGE_RGB, "UNSUPPORTED_COLOR_MODE", "Pixel edits currently require RGBA sprites.");
    auto target = findLayer(sprite, integer(params, "layerId", 1, INT32_MAX));
    require(target->isImage(), "UNSUPPORTED_LAYER", "An image layer is required for drawing.");
    editable(target);
    require(!target->isBackground(), "UNSUPPORTED_LAYER", "Pixel edits currently require a transparent layer.");
    auto frame = integer(params, "frame", 0, sprite->totalFrames() - 1);
    auto cel = target->cel(frame);
    require(!cel || cel->links() == 0, "LINKED_CEL", "Unlink the cel before editing; implicit edits across frames are refused.");
    return target;
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
                  const gfx::Point& position, const std::string& label) {
    if (region.isEmpty()) return;
    auto cel = target->cel(frame);
    // An absent cel has no image to preserve, but the patch's unpainted pixels
    // must be transparent (including holes in shapes).
    UIContext::instance()->activeEditor()->setLayer(target);
    UIContext::instance()->activeEditor()->setFrame(frame);
    Transaction transaction(UIContext::instance(), label);
    if (cel) transaction.execute(new cmd::PatchCel(cel, patch.get(), region, position));
    else {
      auto created = std::make_shared<Cel>(frame, patch);
      created->setPosition(position);
      transaction.execute(new cmd::AddCel(target, created));
    }
    finish(transaction, document);
  }
  void setPixels(Document* document, const Json& params) {
    auto sprite = document->sprite();
    auto target = paintLayer(document, params);
    auto frame = integer(params, "frame", 0, sprite->totalFrames() - 1);
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
      patch->putPixel(pixel.x - bounds.x, pixel.y - bounds.y, pixel.color);
      region |= gfx::Region(gfx::Rect(pixel.x - bounds.x, pixel.y - bounds.y, 1, 1));
    }
    auto label = params.contains("label") ? text(params, "label", 120) : "AI pixel edit";
    applyPatch(document, target, frame, patch, region, gfx::Point(bounds.x, bounds.y), label);
  }
  void draw(Document* document, const Json& params, const std::string& method) {
    auto sprite = document->sprite();
    auto target = paintLayer(document, params);
    auto frame = integer(params, "frame", 0, sprite->totalFrames() - 1);
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
      // Flood against a full canvas of this cel ONLY, not the visible composite.
      // Pixel sampling remains stable while the callback writes the mask.
      ImageRef source(Image::create(IMAGE_RGB, sprite->width(), sprite->height()));
      source->clear(0);
      if (auto cel = target->cel(frame)) doc::copy_image(source.get(), cel->image(), cel->x(), cel->y());
      doc::algorithm::floodfill(source.get(), nullptr, x, y, sprite->bounds(), tolerance, contiguous, mask.get(),
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
        if (x < sprite->width() && mask->getPixel(x, y)) {
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
        bool hasProperties = params.contains("name") || params.contains("opacity") || params.contains("visible");
        require(layer->isEditable() || !hasProperties, "LAYER_LOCKED", "Unlock the layer in a separate request before modifying its properties.");
        require(hasProperties || params.contains("editable"), "INVALID_PARAMS", "Supply at least one layer property.");
        auto name = params.contains("name") ? text(params, "name", 120) : layer->name();
        int opacity = -1;
        if (params.contains("opacity")) {
          require(layer->isImage() && !layer->isBackground(), "UNSUPPORTED_LAYER", "Opacity changes require a transparent image layer.");
          opacity = integer(params, "opacity", 0, 255);
        }
        auto flags = int(layer->flags());
        for (auto entry : {std::make_pair("visible", LayerFlags::Visible), std::make_pair("editable", LayerFlags::Editable)})
          if (params.contains(entry.first)) flags = boolean(params, entry.first) ? flags | int(entry.second) : flags & ~int(entry.second);
        bool changed = name != layer->name() || flags != int(layer->flags()) ||
          (opacity >= 0 && opacity != static_cast<LayerImage*>(layer)->opacity());
        if (changed) {
          Transaction transaction(UIContext::instance(), "AI update layer");
          if (name != layer->name()) transaction.execute(new cmd::SetLayerName(layer, name));
          if (flags != int(layer->flags())) transaction.execute(new cmd::SetLayerFlags(layer, LayerFlags(flags)));
          if (opacity >= 0 && opacity != static_cast<LayerImage*>(layer)->opacity()) transaction.execute(new cmd::SetLayerOpacity(static_cast<LayerImage*>(layer), opacity));
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
    static const std::vector<std::string> methods = {"status", "set_paused", "list_documents", "inspect", "render", "create", "open", "set_pixels", "undo", "redo", "save", "create_layer", "update_layer", "move_layer", "remove_layer", "add_frame", "remove_frame", "set_frame_duration", "draw_shape", "draw_stroke", "flood_fill", "list_assets", "preview_asset", "contact_sheet", "render_onion_skin", "export_png", "export_sprite_sheet"};
    require(std::find(methods.begin(), methods.end(), method) != methods.end(), "METHOD_NOT_FOUND", "Unknown bridge method.");
    if (method == "status") return {{"protocolVersion", 1}, {"bridgeVersion", "0.3.0"}, {"methods", methods}, {"sessionId", m_session}, {"paused", m_paused}, {"assetRoot", m_root.string()}, {"pid", getpid()}};
    require(text(params, "sessionId", 128) == m_session, "SESSION_MISMATCH", "This request belongs to a different editor process.");
    if (method == "set_paused") {
      require(params.contains("paused") && params["paused"].is_boolean(), "INVALID_PARAMS", "paused must be boolean.");
      m_paused = params["paused"].get<bool>();
      return {{"paused", m_paused}, {"sessionId", m_session}};
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
    bool read = method == "inspect" || method == "render" || method == "contact_sheet" || method == "render_onion_skin";
    require(read || !m_paused, "PAUSED", "Bridge is paused. Explicitly resume before modifying documents.");
    if (method == "create") {
      require(ctx->documents().size() < 32, "LIMIT_EXCEEDED", "At most 32 documents may be opened through this bridge.");
      int width = integer(params, "width", 1, 1024), height = integer(params, "height", 1, 1024);
      std::unique_ptr<Sprite> sprite(Sprite::createBasicSprite(IMAGE_RGB, width, height, 256));
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
      return renderFrame(document, params);
    }
    require(ctx->activeDocument() == document, "INACTIVE_DOCUMENT", "Target must be the active GUI document. Refusing to switch silently.");
    if (method == "export_png" || method == "export_sprite_sheet") {
      DocumentReader reader(document, 0);
      checkRevision(document, params);
      return exportPng(document, params, method == "export_sprite_sheet");
    }
    // Check and mutate under the same lock, on the same UI tick.
    ContextWriter writer(ctx, 0);
    checkRevision(document, params);
    SelectionGuard selection(document);
    Json extra = Json::object();
    if (method == "set_pixels") {
      // setPixels owns its transaction but reuses this writer lock.
      setPixels(document, params);
    } else if (method == "draw_shape" || method == "draw_stroke" || method == "flood_fill") {
      draw(document, params, method);
    } else if (method == "create_layer" || method == "update_layer" || method == "move_layer" || method == "remove_layer") {
      extra = editLayers(document, params, method);
    } else if (method == "add_frame" || method == "remove_frame" || method == "set_frame_duration") {
      extra = editFrames(document, params, method);
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
    if (method == "create_layer" || method == "add_frame") App::instance()->mainWindow()->popTimeline();
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
