# Phonon 2 Studio

**Private speech recognition that feels instant on Windows.**

Phonon 2 Studio is a polished desktop interface for [Phonon-2](https://github.com/fermionresearch/phonon), with a Windows live microphone bridge that uses Phonon's native WebSocket streaming protocol. Speak naturally and watch partial transcripts arrive while you talk — no cloud account, no upload, no subscription.

![Phonon 2 Studio](https://img.shields.io/badge/Phonon--2-local%20speech%20recognition-7c6cff?style=for-the-badge)
![Windows](https://img.shields.io/badge/Windows-live%20microphone-38d6a3?style=for-the-badge)
![Privacy](https://img.shields.io/badge/privacy-100%25%20offline-f2b866?style=for-the-badge)

## Why people will love it

- **Real-time Windows inference** — continuous 16 kHz microphone PCM over a persistent local WebSocket.
- **Partial transcripts** — words appear as Phonon emits them, with final phrases replacing temporary hypotheses cleanly.
- **100% local** — audio and text stay on your machine.
- **Beautiful studio UI** — file transcription, live dictation, hotwords, JSON timestamps, transcript export, and API controls.
- **OpenAI-compatible server** — start a local endpoint for your own tools at `127.0.0.1`.
- **No duplicate words** — partial and final updates are handled as separate transcript states.

## Quick start on Windows

Install Python 3.10+ and open PowerShell in this folder:

```powershell
python -m venv .phonon-venv
.\.phonon-venv\Scripts\python.exe -m pip install -r requirements.txt
.\.phonon-venv\Scripts\python.exe phonon_desktop.py
```

Or double-click `run_phonon_desktop.bat` after installing the dependencies.

The first transcription downloads and verifies the Phonon-2 model. The model is cached locally afterwards.

## Live mode

1. Start the app.
2. Click **Start listening**.
3. Speak into your Windows microphone.
4. Watch partial text appear in the transcript canvas.
5. Click **Stop live transcription** to finalize the stream.

The app starts a loopback-only Phonon server on port `18001`, then streams raw microphone PCM through:

```text
ws://127.0.0.1:18001/v1/audio/stream
```

This is the same streaming protocol documented by the Phonon project, adapted for Windows microphone capture.

## Features

| Feature | Description |
| --- | --- |
| File transcription | WAV, FLAC, OGG, AIFF, and other formats supported by the local backend |
| Live microphone | Continuous Windows capture with partial and final transcript events |
| Hotwords | Bias recognition toward names, products, places, and technical terms |
| JSON output | Preserve Phonon response data and word timestamps |
| Transcript export | Save the current canvas as TXT or JSON |
| Local API | Start an OpenAI-compatible endpoint for local integrations |
| Engine status | See CPU engine, privacy state, and current activity |

## Requirements

- Windows 10 or 11
- Python 3.10 or newer
- A microphone for live mode
- CPU with SSE4.1; AVX2 is recommended
- Approximately 1 GB free disk space for Python packages, cache, and model files

Windows CPU inference speed depends on the processor. The live protocol is seamless and low-latency, but recognition throughput is hardware-dependent.

## Responsible use

Phonon-2 is an English speech-recognition model. Review important transcripts before relying on them. Do not record people without appropriate consent, and follow the model and dependency licenses.

## Credits and license

Phonon 2 Studio is released under the MIT License. Phonon-2 model weights are distributed by Fermion Research under CC-BY-4.0; the Phonon runtime is maintained by Fermion Research under its own license.

## Star the project

If this makes private Windows dictation useful for you, star the repository, share it with someone who values local AI, and open an issue with your microphone model and CPU so the Windows experience can keep improving.
