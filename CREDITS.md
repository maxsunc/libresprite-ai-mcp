# Credits and third-party notices

LibreSprite AI MCP is an **independent development project**, not an official
LibreSprite release and not endorsed by its maintainers. The native editor is a
modified LibreSprite build; the MCP bridge and server are this project's work.

## LibreSprite and its origins

Thank you to the [LibreSprite contributors](https://github.com/LibreSprite/LibreSprite)
for the editor on which this integration is built, and to David Capello and the
original Aseprite contributors for the GPL-era code and component libraries
retained in LibreSprite. This repository imports LibreSprite **v1.2**, commit
`5cb089be32f56b4ae559ae51f0c5666049f41bca`, with its pinned dependencies as
ordinary source files.

- [Upstream GPLv2 license](vendor/libresprite/LICENSE.txt)
- [Original project overview](vendor/libresprite/README.md)
- [Original contributor, palette, algorithm, and library acknowledgments](vendor/libresprite/CONTRIBUTORS.md)
- [Pinned upstream and dependency provenance](vendor/libresprite.upstream.json)
- [Our dated native changes](docs/native-changes.md)

Upstream acknowledgments include palettes by Richard "DawnBringer" Fhager and
Arne Niklas Jansson; RotSprite by Xenowhirl; and pixel-perfect drawing work by
Sébastien Bénard and Carduus. Their original notices and links remain in the
upstream contributor file. Credits do not replace the applicable licenses.

## Retained component licenses

This index helps locate notices; it does not relicense third-party material or
replace the full terms and copyright notices in the files. Other LibreSprite
component libraries also retain their adjacent `LICENSE.txt` and file headers.

| Component | Retained terms / notices |
| --- | --- |
| Aseprite document library | [MIT](vendor/libresprite/src/doc/LICENSE.txt) |
| Base library | [MIT](vendor/libresprite/src/base/LICENSE.txt) |
| Graphics library | [MIT](vendor/libresprite/src/gfx/LICENSE.txt) |
| Renderer | [MIT](vendor/libresprite/src/render/LICENSE.txt) |
| UI library | [MIT](vendor/libresprite/src/ui/LICENSE.txt) |
| System/platform library | [MIT](vendor/libresprite/src/she/LICENSE.txt) |
| `clip` clipboard library | [MIT](vendor/libresprite/src/clip/LICENSE.txt) |
| `flic` animation codec | [MIT](vendor/libresprite/src/flic/LICENSE.txt) |
| `undo` library | [MIT](vendor/libresprite/src/undo/LICENSE.txt) |
| Duktape JavaScript engine | [MIT](vendor/libresprite/third_party/duktape/LICENSE.txt), [authors](vendor/libresprite/third_party/duktape/AUTHORS.rst) |
| SimpleIni | [MIT](vendor/libresprite/third_party/simpleini/LICENCE.txt) |
| Observable | [MIT](vendor/libresprite/third_party/observable/LICENSE.txt) |
| MODP base64 | [BSD-style terms](vendor/libresprite/third_party/modp_b64/LICENSE) |
| EasyTab | [Public-domain dedication / Unlicense](vendor/libresprite/third_party/EasyTab/LICENSE) |
| QOI | [MIT notice embedded in the header](vendor/libresprite/third_party/qoi/qoi.h) |
| nlohmann/json 3.11.3 | [MIT](vendor/nlohmann/LICENSE.MIT), [pinned provenance](vendor/nlohmann.upstream.json) |

LibreSprite also retains notices for externally supplied libraries, including
[giflib](vendor/libresprite/docs/licenses/giflib-LICENSE.txt),
[libjpeg](vendor/libresprite/docs/licenses/libjpeg-LICENSE.txt),
[libpng](vendor/libresprite/docs/licenses/libpng-LICENSE.txt),
[Google Test](vendor/libresprite/docs/licenses/gtest-LICENSE.txt), and
[XFree86/X11](vendor/libresprite/docs/licenses/xfree86-LICENSE.txt).
Native dependencies installed through the platform package manager retain their
own licenses. If distributing a binary bundle, review the actual linked/bundled
dependency versions and include their required notices and corresponding source
where applicable; this source index is not a binary-distribution compliance bundle.

## MCP server dependencies

The TypeScript server uses the [Model Context Protocol TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
and [Zod](https://github.com/colinhacks/zod), both MIT-licensed. Development tools
include TypeScript (Apache-2.0) and Node.js type definitions from DefinitelyTyped
(MIT). The lockfile records the installed dependency graph; npm dependencies are
not vendored into this source repository and retain their package notices.

## Project and artwork licensing

Project-authored integration code is **GPL-2.0-only**; see [LICENSE](LICENSE) and
[the licensing overview](LICENSE.md). Existing upstream files keep their original
file-level licenses and copyright notices.

The local working artwork collection is not included in this repository.
Independently created artwork is not automatically GPL-licensed by using the
editor; any shared examples need their own explicit ownership and license review.
