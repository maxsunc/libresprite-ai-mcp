// LibreSprite AI bridge. Distributed under GNU GPL version 2.
#include "app/automation/bridge.h"

#if defined(__APPLE__) || defined(__linux__)
#include "app/app.h"
#include "app/cmd/add_cel.h"
#include "app/cmd/patch_cel.h"
#include "app/context_access.h"
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
#include "doc/documents.h"
#include "doc/frame_tag.h"
#include "doc/image.h"
#include "doc/layer.h"
#include "doc/layers_range.h"
#include "doc/palette.h"
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
    require(size_t(sprite->width()) * size_t(sprite->height()) <= MaxPixels && sprite->totalFrames() <= 256,
            "LIMIT_EXCEEDED", "This first bridge supports at most 1,048,576 canvas pixels and 256 frames.");
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
  Json renderFrame(Document* document, const Json& params) {
    auto sprite = document->sprite();
    auto frame = integer(params, "frame", 0, sprite->totalFrames() - 1);
    auto scale = integer(params, "scale", 1, 16);
    require(size_t(sprite->width()) * sprite->height() * scale * scale <= MaxPixels, "LIMIT_EXCEEDED", "Preview exceeds 1,048,576 output pixels. Use a smaller scale.");
    std::unique_ptr<Image> image(Image::create(IMAGE_RGB, sprite->width(), sprite->height()));
    image->clear(0);
    render::Render renderer;
    renderer.setBgType(render::BgType::TRANSPARENT);
    renderer.renderSprite(image.get(), sprite, frame);
    std::shared_ptr<she::Surface> surface(she::instance()->createRgbaSurface(sprite->width() * scale, sprite->height() * scale), [](she::Surface* surface) { surface->dispose(); });
    require(bool(surface), "RENDER_FAILED", "Cannot allocate preview surface.");
    for (int y = 0; y < surface->height(); ++y)
      for (int x = 0; x < surface->width(); ++x) surface->putPixel(image->getPixel(x / scale, y / scale), x, y);
    std::string encoded;
    base::encode_base64(she::instance()->encodeSurfaceAsPNG(surface.get()), encoded);
    auto result = inspect(document);
    result["pngBase64"] = encoded; result["frame"] = frame; result["scale"] = scale;
    return result;
  }
  void setPixels(Document* document, const Json& params) {
    auto sprite = document->sprite();
    require(sprite->pixelFormat() == IMAGE_RGB, "UNSUPPORTED_COLOR_MODE", "Pixel edits currently require RGBA sprites.");
    auto layerId = integer(params, "layerId", 1, INT32_MAX);
    Layer* target = nullptr;
    for (auto layer : sprite->layers()) if (layer->id() == ObjectId(layerId)) target = layer;
    require(target && target->isImage(), "LAYER_NOT_FOUND", "An image layer in this document is required.");
    for (auto layer = target; layer; layer = layer->parent())
      require(layer->isEditable(), "LAYER_LOCKED", "Target layer or its parent is locked.");
    require(!target->isBackground(), "UNSUPPORTED_LAYER", "Pixel edits currently require a transparent layer.");
    auto frame = integer(params, "frame", 0, sprite->totalFrames() - 1);
    auto cel = target->cel(frame);
    require(!cel || cel->links() == 0, "LINKED_CEL", "Unlink the cel before editing; implicit edits across frames are refused.");
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
    UIContext::instance()->activeEditor()->setLayer(target);
    UIContext::instance()->activeEditor()->setFrame(frame);
    Transaction transaction(UIContext::instance(), label);
    if (cel) transaction.execute(new cmd::PatchCel(cel, patch.get(), region, gfx::Point(bounds.x, bounds.y)));
    else {
      auto created = std::make_shared<Cel>(frame, patch);
      created->setPosition(bounds.x, bounds.y);
      transaction.execute(new cmd::AddCel(target, created));
    }
    transaction.commit();
    document->notifyGeneralUpdate();
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
    static const std::vector<std::string> methods = {"status", "set_paused", "list_documents", "inspect", "render", "create", "open", "set_pixels", "undo", "redo", "save"};
    require(std::find(methods.begin(), methods.end(), method) != methods.end(), "METHOD_NOT_FOUND", "Unknown bridge method.");
    if (method == "status") return {{"protocolVersion", 1}, {"sessionId", m_session}, {"paused", m_paused}, {"assetRoot", m_root.string()}, {"pid", getpid()}};
    require(text(params, "sessionId", 128) == m_session, "SESSION_MISMATCH", "This request belongs to a different editor process.");
    if (method == "set_paused") {
      require(params.contains("paused") && params["paused"].is_boolean(), "INVALID_PARAMS", "paused must be boolean.");
      m_paused = params["paused"].get<bool>();
      return {{"paused", m_paused}, {"sessionId", m_session}};
    }
    uiIdle();
    if (method == "list_documents") {
      Json documents = Json::array();
      for (auto item : ctx->documents()) {
        auto document = static_cast<Document*>(item);
        DocumentReader reader(document, 0);
        documents.push_back(summary(document));
      }
      return {{"documents", documents}, {"activeDocumentId", ctx->activeDocument() ? Json(ctx->activeDocument()->id()) : Json(nullptr)}, {"paused", m_paused}, {"sessionId", m_session}};
    }
    bool read = method == "inspect" || method == "render";
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
      require(fs::is_regular_file(path) && fs::file_size(path) <= 32 * 1024 * 1024, "LIMIT_EXCEEDED", "Open requires a regular file of at most 32 MiB.");
      require(path.extension() == ".ase" || path.extension() == ".aseprite" || path.extension() == ".png", "UNSUPPORTED_FORMAT", "Opening currently supports native sprites and PNG.");
      std::unique_ptr<FileOp> operation(FileOp::createLoadDocumentOperation(nullptr, path.c_str(), FILE_LOAD_SEQUENCE_NONE));
      operation->operate(); operation->done(); operation->postLoad();
      require(!operation->hasError(), "OPEN_FAILED", operation->error());
      std::unique_ptr<Document> document(operation->releaseDocument());
      require(bool(document), "OPEN_FAILED", "File did not produce a document.");
      // Validate working limits before attaching a document to the GUI.
      inspect(document.get());
      document->setContext(ctx); auto result = inspect(document.get()); document.release();
      return result;
    }
    auto document = findDocument(params);
    if (read) {
      DocumentReader reader(document, 0);
      return method == "inspect" ? inspect(document) : renderFrame(document, params);
    }
    require(ctx->activeDocument() == document, "INACTIVE_DOCUMENT", "Target must be the active GUI document. Refusing to switch silently.");
    // Check and mutate under the same lock, on the same UI tick.
    ContextWriter writer(ctx, 0);
    checkRevision(document, params);
    if (method == "set_pixels") {
      // setPixels owns its transaction but reuses this writer lock.
      setPixels(document, params);
    } else if (method == "undo" || method == "redo") {
      auto history = document->undoHistory();
      require(method == "undo" ? history->canUndo() : history->canRedo(), "NO_HISTORY", "No matching undo/redo state.");
      if (method == "undo") history->undo(); else history->redo();
      document->generateMaskBoundaries(); document->notifyGeneralUpdate();
    } else if (method == "save") save(document, params);
    else throw BridgeError("METHOD_NOT_FOUND", "Unknown bridge method.");
    update_screen_for_document(document);
    return inspect(document);
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
