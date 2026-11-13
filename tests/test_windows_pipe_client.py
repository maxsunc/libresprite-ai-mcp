"""Windows native-suite byte-pipe adapter: fragmentation, buffering and timeout. GPLv2."""
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest
import uuid

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(os.name == "nt", "Windows named pipes only")
class WindowsPipeClientTest(unittest.TestCase):
    def test_fragmented_buffered_lines_and_timeout(self):
        spec = importlib.util.spec_from_file_location("windows_pipe_client", ROOT / "scripts/windows_pipe_client.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        endpoint = r"\\.\pipe\libresprite-ai-python-" + uuid.uuid4().hex
        script = """
const net = require('node:net');
const server = net.createServer(socket => {
  socket.on('data', () => {
    socket.write('frag');
    setTimeout(() => socket.write('mented\\nsecond\\n'), 10);
  });
});
server.listen(process.argv[1], () => console.log('ready'));
"""
        process = subprocess.Popen(["node", "-e", script, endpoint], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(process.stdout.close)
        self.addCleanup(process.stderr.close)
        self.addCleanup(lambda: (process.terminate(), process.wait(timeout=5)))
        self.assertEqual(process.stdout.readline().strip(), "ready")
        client = module.WindowsPipeClient(endpoint)
        self.addCleanup(client.close)
        self.assertEqual(client.getpeername(), endpoint)
        self.assertIs(client.makefile("rb"), client)
        client.sendall(b"request\n")
        self.assertEqual(client.readline(), b"fragmented\n")
        self.assertEqual(client.readline(), b"second\n")
        client.settimeout(.02)
        with self.assertRaises(TimeoutError):
            client.readline()
        client.close()
        client.close()
