"""CosyVoice 2 TTS server for `--tts-url`: POST /tts {"text": ...} -> 16 kHz mono int16 PCM, streamed per chunk.

Run it from a CosyVoice checkout (github.com/FunAudioLLM/CosyVoice, model pretrained_models/CosyVoice2-0.5B) on a GPU
box and reach it over an ssh tunnel; it listens on localhost only:
  PORT=50021 python3 cosyvoice_server.py        # then: ssh -N -L 127.0.0.1:50021:127.0.0.1:50021 gpu-box
The voice is the zero-shot prompt below (PROMPT_WAV, a 16-bit wav, and what is said in it).  A prompt of a whole
number of seconds (n x 25 speech tokens) saves the first-chunk padding: about 0.2 s sooner to the first sound.
Checked on a DGX Spark (GB10, torch 2.13 cu130): first chunk about 1.05 s, real-time factor about 0.55.  Two fixes to
the CosyVoice checkout were needed there: load_wav (cosyvoice/utils/file_utils.py) read with the `wave` module, as
torchaudio 2.9+ wants torchcodec; and CosyVoice2Model.tts kept its growing token_hop_len in a local, as it grew
self.token_hop_len for good, so from the second request on the first chunk waited for about 4 s of speech.
"""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path[:0] = [os.getcwd(), os.path.join(os.getcwd(), "third_party/Matcha-TTS")]
import torch, torchaudio
from cosyvoice.cli.cosyvoice import CosyVoice2

MODEL = CosyVoice2("pretrained_models/CosyVoice2-0.5B", load_jit=False, load_trt=False, fp16=False)   # fp32 is faster than fp16 autocast here
PROMPT_WAV = os.environ.get("PROMPT_WAV", "asset/zero_shot_prompt_16pad.wav")    # 4.0 s = 100 tokens
PROMPT_TEXT = os.environ.get("PROMPT_TEXT", "希望你以后能够做的比我还好呦。")
MODEL.add_zero_shot_spk(PROMPT_TEXT, PROMPT_WAV, "pet")   # prompt features once, not per request
for _ in MODEL.inference_zero_shot("你好呀，我在。", "", "", zero_shot_spk_id="pet", stream=True):
    pass                         # warm-up: the first request is about 0.8 s slower
RESAMPLE = torchaudio.transforms.Resample(MODEL.sample_rate, 16000)
LOCK = threading.Lock()          # one synthesis at a time on the GPU


def pcm16(t):
    return (RESAMPLE(t.float().cpu()).clamp(-1, 1) * 32767).to(torch.int16).numpy().tobytes()


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        text = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["text"]
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        with LOCK:
            for out in MODEL.inference_zero_shot(text, "", "", zero_shot_spk_id="pet", stream=True):
                b = pcm16(out["tts_speech"])
                self.wfile.write(b"%x\r\n" % len(b) + b + b"\r\n")
                self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", 50021))), H).serve_forever()
