"""Dependency-free APNG/GIF checks for test-owned exported animations. GPLv2.

These deliberately narrow readers verify our full-canvas APNG and noninterlaced
GIF output independently of LibreSprite's codecs. Not general asset decoders.
"""
import struct
import zlib


def read_apng(path, smoke):
    png = path.read_bytes()
    assert png.startswith(smoke.SIGNATURE)
    offset, sequence = 8, 0
    frames, controls = [], []
    compressed = bytearray()
    header, animation = None, None
    ended = False

    def finish_frame():
        if controls:
            assert compressed
            # Reconstruct a standalone PNG and use the pixel-exact PNG reader.
            frame_path = path.with_name("checked-apng-frame.png")
            frame_path.write_bytes(smoke.SIGNATURE + smoke.chunk(b"IHDR", header) + smoke.chunk(b"IDAT", bytes(compressed)) + smoke.chunk(b"IEND", b""))
            frames.append(smoke.read_png(frame_path))
            compressed.clear()

    while offset + 12 <= len(png):
        size = struct.unpack_from(">I", png, offset)[0]
        kind = png[offset + 4:offset + 8]
        data = png[offset + 8:offset + 8 + size]
        assert len(data) == size
        assert struct.unpack_from(">I", png, offset + 8 + size)[0] == zlib.crc32(kind + data)
        if kind == b"IHDR":
            assert header is None and offset == 8
            header = data
        elif kind == b"acTL":
            assert header and animation is None and not controls
            animation = struct.unpack(">II", data)
        elif kind == b"fcTL":
            assert animation
            finish_frame()
            control = struct.unpack(">IIIIIHHBB", data)
            assert control[0] == sequence
            sequence += 1
            assert control[1:3] == struct.unpack_from(">II", header)
            assert control[3:5] == (0, 0) and control[6] == 1000
            assert control[7:] == (0, 0)  # NONE disposal, SOURCE blending
            controls.append(control)
        elif kind in (b"IDAT", b"fdAT"):
            assert controls
            if kind == b"IDAT":
                assert len(controls) == 1
            else:
                assert len(controls) > 1 and struct.unpack_from(">I", data)[0] == sequence
                sequence += 1
                data = data[4:]
            compressed.extend(data)
        elif kind == b"IEND":
            finish_frame()
            ended = True
        else:
            raise AssertionError("Unexpected APNG chunk: " + str(kind))
        offset += size + 12
        if ended:
            break
    assert ended and offset == len(png) and animation[0] == len(frames)
    return {"frames": frames, "durations": [control[5] for control in controls], "plays": animation[1]}


def gif_lzw(data, minimum):
    clear, stop = 1 << minimum, (1 << minimum) + 1
    table, bits, next_code, previous = {}, minimum + 1, stop + 1, None
    offset = 0
    decoded = bytearray()
    while offset + bits <= len(data) * 8:
        code = sum(((data[(offset + i) // 8] >> ((offset + i) % 8)) & 1) << i for i in range(bits))
        offset += bits
        if code == clear:
            table = {i: bytes((i,)) for i in range(clear)}
            bits, next_code, previous = minimum + 1, stop + 1, None
            continue
        if code == stop:
            return decoded
        if code in table:
            entry = table[code]
        else:
            assert code == next_code and previous is not None
            entry = previous + previous[:1]
        decoded.extend(entry)
        if previous is not None and next_code < 4096:
            table[next_code] = previous + entry[:1]
            next_code += 1
            if next_code == 1 << bits and bits < 12:
                bits += 1
        previous = entry
    raise AssertionError("GIF LZW stream has no stop code")


def read_gif(path):
    gif = path.read_bytes()
    assert gif[:6] in (b"GIF87a", b"GIF89a")
    width, height, packed, background, _ = struct.unpack_from("<HHBBB", gif, 6)
    offset = 13

    def palette(count):
        nonlocal offset
        result = [tuple(gif[offset + 3 * i:offset + 3 * i + 3]) + (255,) for i in range(count)]
        offset += 3 * count
        return result

    def blocks():
        nonlocal offset
        result = bytearray()
        while gif[offset]:
            size = gif[offset]
            result.extend(gif[offset + 1:offset + 1 + size])
            offset += size + 1
        offset += 1
        return bytes(result)

    global_palette = palette(1 << ((packed & 7) + 1)) if packed & 128 else None
    canvas = bytearray(width * height * 4)
    gce, plays = (0, 0, None), 1
    frames, durations = [], []
    previous_canvas = None
    while gif[offset] != 0x3B:
        kind = gif[offset]
        offset += 1
        if kind == 0x21:
            label = gif[offset]
            offset += 1
            extension = blocks()
            if label == 0xF9:
                flags, delay, transparent = struct.unpack("<BHB", extension)
                gce = ((flags >> 2) & 7, delay * 10, transparent if flags & 1 else None)
            elif label == 0xFF and extension.startswith(b"NETSCAPE2.0"):
                repeats = struct.unpack_from("<H", extension, 12)[0]
                plays = 0 if repeats == 0 else repeats + 1
            continue
        assert kind == 0x2C
        x, y, w, h, flags = struct.unpack_from("<HHHHB", gif, offset)
        offset += 9
        assert not flags & 64 and x + w <= width and y + h <= height
        colors = palette(1 << ((flags & 7) + 1)) if flags & 128 else global_palette
        minimum = gif[offset]
        offset += 1
        indices = gif_lzw(blocks(), minimum)
        assert len(indices) == w * h
        disposal, duration, transparent = gce
        previous_canvas = canvas[:]
        for dy in range(h):
            for dx in range(w):
                index = indices[dy * w + dx]
                if index != transparent:
                    position = ((y + dy) * width + x + dx) * 4
                    canvas[position:position + 4] = bytes(colors[index])
        frames.append((width, height, bytes(canvas)))
        durations.append(duration)
        if disposal == 2:
            clear = bytes(4) if transparent is not None else bytes(global_palette[background])
            for dy in range(h):
                position = ((y + dy) * width + x) * 4
                canvas[position:position + w * 4] = clear * w
        elif disposal == 3:
            canvas = previous_canvas
        gce = (0, 0, None)
    assert offset + 1 == len(gif)
    return {"frames": frames, "durations": durations, "plays": plays}
