// Test harness for GUI-independent APNG assembly. Distributed under GPLv2.
#include "app/automation/apng.h"
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>

int main(int argc, char** argv) {
  try {
    if (argc < 5 || (argc - 4) % 2) return 2;
    app::automation::ApngEncoder encoder(std::stoul(argv[2]), std::stoi(argv[3]) != 0);
    for (int i = 4; i < argc; i += 2) {
      std::ifstream input(argv[i], std::ios::binary);
      if (!input) return 2;
      std::vector<uint8_t> png((std::istreambuf_iterator<char>(input)), {});
      encoder.append(png, std::stoul(argv[i + 1]));
    }
    auto bytes = encoder.finish();
    std::ofstream output(argv[1], std::ios::binary);
    output.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    return output ? 0 : 2;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
