"""Phase 4: 把双人对话脚本合成为一期音频。

使用已配置的语音合成 2.0 双音色与语音指令，逐轮合成并保留时间轴。
默认云端失败就报错；只有显式 allow_local=True 才允许系统语音降级。
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
import hashlib
import wave
from pathlib import Path

import requests

import config

ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
RESOURCE_ID = "seed-tts-2.0"
TURN_RE = re.compile(r"^(甲|乙)[：:]\s*(.+)$")


def parse_turns(script: str) -> list[tuple[str, str]]:
    """返回 [(speaker_voice_id, text), ...]"""
    voice_a = config.require(config.VOLC_VOICE_HOST_A, "VOLC_VOICE_HOST_A", "在 .env 里配置甲的音色 ID")
    voice_b = config.require(config.VOLC_VOICE_HOST_B, "VOLC_VOICE_HOST_B", "在 .env 里配置乙的音色 ID")
    turns = []
    for line in script.splitlines():
        m = TURN_RE.match(line.strip())
        if m:
            voice = voice_a if m.group(1) == "甲" else voice_b
            turns.append((voice, m.group(2)))
    return turns


def _tts_one(api_key: str, voice: str, text: str) -> bytes:
    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    style = (
        "像和熟悉的朋友录制中文科技播客，带着好奇自然地提出问题。声音放松，短句之间有轻微停顿，语速适中。"
        if voice == config.VOLC_VOICE_HOST_A else
        "像和熟悉的朋友录制中文科技播客，温和、清晰地解释一个有意思的发现。语气自然，有交流感，重点处稍作停顿，语速适中。"
    )
    body = {
        "req_params": {
            "text": text,
            "speaker": voice,
            "audio_params": {"format": "mp3", "sample_rate": 24000},
            "additions": json.dumps({"context_texts": [style]}, ensure_ascii=False),
        }
    }
    cache_dir = config.OUTPUT_DIR / "tts_segments"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    cache_file = cache_dir / (cache_key + ".mp3")
    if cache_file.exists() and cache_file.stat().st_size > 0:
        return cache_file.read_bytes()
    resp = requests.post(ENDPOINT, headers=headers, json=body, timeout=60)
    resp.raise_for_status()

    # 响应按 HTTP chunked 分块返回，每块是独立 JSON 对象，逐块解码拼接 base64 音频
    import base64
    audio = bytearray()
    decoder = json.JSONDecoder()
    text_buf = resp.text
    pos = 0
    while pos < len(text_buf):
        while pos < len(text_buf) and text_buf[pos] in "\r\n \t":
            pos += 1
        if pos >= len(text_buf):
            break
        obj, end = decoder.raw_decode(text_buf, pos)
        pos = end
        # code=0：单块音频正常；code=20000000：整段流结束标记；其余视为报错
        if obj.get("code") not in (0, 20000000, None):
            raise RuntimeError(f"TTS 报错: {obj.get('message')} (text={text[:20]!r})")
        if obj.get("data"):
            audio.extend(base64.b64decode(obj["data"]))
    if not audio:
        raise RuntimeError(f"没收到音频数据 (text={text[:20]!r})")
    cache_file.write_bytes(bytes(audio))
    return bytes(audio)


def _synthesize_cloud(script: str) -> Path:
    api_key = config.require(config.VOLC_SPEECH_API_KEY, "VOLC_SPEECH_API_KEY", "在 .env 里填入")
    turns = parse_turns(script)
    if not turns:
        raise RuntimeError("脚本里没有解析到 '甲：'/'乙：' 格式的对话行，检查 script.md 格式")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pcm_parts = []
        timeline = []
        position = 0.0
        for i, (voice, text) in enumerate(turns):
            audio = _tts_one(api_key, voice, text)
            seg_path = tmp_path / f"seg_{i:04d}.mp3"
            seg_path.write_bytes(audio)
            decoded = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(seg_path), "-f", "s16le", "-ac", "1", "-ar", "24000", "pipe:1"],
                check=True, capture_output=True,
            ).stdout
            if not decoded:
                raise RuntimeError("语音分段无法解码")
            duration = len(decoded) / 48000
            timeline.append({"speaker": "甲" if voice == config.VOLC_VOICE_HOST_A else "乙", "voice": voice,
                             "text": text, "start": round(position, 3), "end": round(position+duration, 3)})
            pcm_parts.append(decoded)
            position += duration
            if i < len(turns)-1:
                pcm_parts.append(bytes(4800))  # 100 ms turn gap at 24 kHz, 16 bit, mono
                position += .1
            print(f"[{i + 1}/{len(turns)}] 合成完成: {text[:20]}...")
        combined = tmp_path / "combined.wav"
        with wave.open(str(combined), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(b"".join(pcm_parts))

        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(combined), "-af", "loudnorm=I=-18:TP=-1.5:LRA=7",
             "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "128k", str(config.EPISODE_PATH)],
            check=True, capture_output=True,
        )
        (config.OUTPUT_DIR / "episode.json").write_text(
            json.dumps({"provider": "volc_tts_2.0", "fallback": False, "duration": round(position,3),
                        "turns": timeline}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(f"合成完成，共 {len(turns)} 句，输出：{config.EPISODE_PATH}")
    return config.EPISODE_PATH


def _synthesize_local(script: str) -> Path:
    turns = []
    for line in script.splitlines():
        match = TURN_RE.match(line.strip())
        if match:
            turns.append((match.group(1), match.group(2)))
    if not turns:
        raise RuntimeError("脚本里没有解析到 '甲：'/'乙：' 格式的对话行，检查 script.md 格式")

    local_voices = {"甲": "Tingting", "乙": "Reed (中文（中国大陆）)"}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        concat_list = tmp_path / "concat.txt"
        lines = []
        for i, (speaker, text) in enumerate(turns):
            seg_path = tmp_path / f"seg_{i:04d}.aiff"
            subprocess.run(
                ["say", "-v", local_voices[speaker], "-r", "165", "-o", str(seg_path), text],
                check=True,
                capture_output=True,
            )
            lines.append(f"file '{seg_path}'")
            print(f"[{i + 1}/{len(turns)}] 本地合成完成: {text[:20]}...")
        concat_list.write_text("\n".join(lines), encoding="utf-8")

        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
             "-c:a", "libmp3lame", "-b:a", "96k", str(config.EPISODE_PATH)],
            check=True,
            capture_output=True,
        )

    print(f"本地降级合成完成，共 {len(turns)} 句，输出：{config.EPISODE_PATH}")
    return config.EPISODE_PATH


def synthesize(script: str | None = None, *, allow_local: bool = False) -> Path:
    if script is None:
        script = config.SCRIPT_PATH.read_text(encoding="utf-8")

    try:
        return _synthesize_cloud(script)
    except requests.ConnectionError as exc:
        if not allow_local:
            raise RuntimeError("云端语音连接失败，未降级为系统朗读") from exc
        print(f"云端 TTS 网络不可达，切换本机双音色合成：{exc}")
        return _synthesize_local(script)


if __name__ == "__main__":
    synthesize()
