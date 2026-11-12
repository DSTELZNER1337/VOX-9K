# Third-party attribution and licensing review

VOX-9K's original code remains under the existing MIT `LICENSE`. That license does not relicense dependencies, models, voices or third-party images. This inventory is based on installed distribution metadata and primary upstream sources checked on 2026-11-11. It is not a completed redistribution compliance review for a packaged binary.

| Component | Observed license / evidence | Distribution note |
| --- | --- | --- |
| Flask 3.1.3 | BSD-3-Clause, installed metadata | Retain applicable copyright and license notices if redistributed. |
| PyKokoro 0.10.4 / OnnxVoice 0.2.5 | Apache-2.0, installed metadata and license files | Preserve upstream licenses and applicable notices. |
| Kokoro-82M weights | Apache-2.0, [official model card](https://huggingface.co/hexgrad/Kokoro-82M) | Exact converted ONNX/voice artifact provenance and notices must also be checked before bundling cache files. |
| Qwen3-TTS 0.6B CustomVoice | Apache-2.0, [official checkpoint](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice) | Model, tokenizer and voice assets remain third-party components. |
| faster-qwen3-tts 0.5.4 | MIT, installed metadata and [upstream license](https://github.com/andimarafioti/faster-qwen3-tts/blob/main/LICENSE) | Preserve the copyright/license if distributing this library. |
| qwen-tts 0.1.1 / qwen-tts-hf 0.1.1.post1 | Apache-2.0, installed metadata | Original and compatibility distribution are distinct; do not conflate them. |
| ONNX Runtime GPU 1.31.0 / CPU 1.31.0 | MIT, installed metadata in respective environments | NVIDIA runtime components retain separate terms. |
| PyTorch 2.11.0+cu126 | BSD-3-Clause, installed metadata | Bundled CUDA components and dependent code have their own notices. |
| Torchaudio 2.11.0+cu126 | License field absent in captured metadata | Verify installed license files and bundled codec notices before redistributing. |
| Transformers 4.57.3 / 5.15.1 | Apache 2.0, installed metadata | No bundled weights are covered by the app's MIT license. |
| FastAPI / Uvicorn / Starlette / httpx | MIT / BSD-3-Clause / BSD-3-Clause / BSD-3-Clause, installed metadata | Preserve applicable notices in distributions. |
| NumPy 2.5.4 | Composite BSD-3-Clause, 0BSD, MIT, Zlib, CC0-1.0, installed metadata | Include its own bundled-library notices if redistributed. |
| lexphon / espeakng-runtime wrappers | Apache-2.0, installed metadata | Wrapper licensing does not establish the license of a separately installed native phonemizer. |

`tools/capture_environment.py` captured 119 installed distributions in `.venv` and 92 in `.venv-fast`, including transitive requirements, license fields/classifiers and declared license filenames. Full results remain local under ignored `audit/environment-*/packages.json`; absent metadata is unresolved, not evidence of a permissive license. No virtual environment, model cache or generated audio should be committed.

## Outstanding provenance checks

- Visual provenance was supplied by the project owner on 2026-11-12; see the asset record below. The earlier audit's missing-provenance finding is resolved for this source publication.
- The page uses Arial/system sans-serif and contains no remote font or third-party JavaScript CDN reference. No font files are bundled. A browser using an installed system font does not establish permission to redistribute the font itself.
- Confirm the license and provenance of the exact cached ONNX model conversion, voice packs and Qwen snapshot/tokenizer. The upstream model cards establish their stated weight licenses, not every locally cached derivative's chain of custody.
- If a native eSpeak NG binary is packaged later, review its [upstream COPYING](https://github.com/espeak-ng/espeak-ng/blob/master/COPYING) and the specific binary distribution. Its terms differ from the Apache-licensed Python wrapper. No native binary was added or redistributed in this audit.
- Retain required license texts and applicable NOTICE/copyright material when bundling third-party software or Apache-licensed model assets. Do not infer that this short attribution file replaces those materials. Exact obligations depend on what is actually distributed.

The original MIT license was not changed. Source-only publication and a future installer that bundles runtimes/models have different attribution and compliance work. Do not describe the entire project, including third-party dependencies and weights, as MIT-licensed. Model and bundled-binary redistribution checks remain separate from this source-only publication.

## Optional Desktop V1 dependencies

The runtime follow-up installed the following optional desktop packages into `.venv`; no previously installed package version changed. `requirements-desktop.txt` pins this tested stack. Browser mode does not import or require pywebview.

| Component | License evidence |
| --- | --- |
| pywebview 6.2.1 | BSD-3-Clause, installed metadata and [official PyPI page](https://pypi.org/project/pywebview/) |
| Bottle 0.13.4 | MIT, installed metadata |
| proxy_tools 0.1.0 | MIT, installed metadata |
| pythonnet 3.2.1 | MIT, installed metadata |
| clr_loader 0.3.1 | MIT, installed `clr_loader-0.3.1.dist-info/licenses/LICENSE`; its metadata license field is blank |

Microsoft Edge WebView2 Runtime is separately licensed; a future installer must follow [Microsoft's runtime distribution guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution). No Microsoft runtime was installed or bundled in this phase; the existing runtime was used. The original application MIT license and all visual assets were preserved. No custom icon is included. The owner subsequently supplied the existing background/screenshot provenance recorded below.


## Included visual assets: owner-supplied provenance

Recorded 2026-11-12 for the source-code publication:

- **background.png:** the owner states that this abstract artwork was custom-generated with OpenAI's ChatGPT image generation tool, under the owner's creative direction specifically for VOX-9K. The owner states it was not downloaded from a stock library or copied from an existing software product.
- **screenshot.png:** the owner identifies this as a screenshot of their application containing that same generated background. The owner supplied the current application screenshot for the follow-up source publication on 2026-11-12; it shows WAV export, background controls and the updated Stelz Tools footer.
- **Permission:** the owner expressly authorizes use, modification and redistribution of this artwork as part of the free, open-source VOX-9K project, including GitHub, desktop application distribution, StelzTools and portfolio materials. The background remains unchanged. The repository screenshot was refreshed with the owner's approved image, copied without editing, for the follow-up source publication.
- **Rights scope:** this records the owner's provenance statement and permission to use/distribute the generated output. It does not establish that the AI-generated artwork is copyright-protected, grant exclusive rights, or guarantee that similar output cannot exist. The existing MIT license covers original application code; third-party dependencies/models retain their own terms.

OpenAI's [Terms of Use](https://openai.com/policies/terms-of-use/) (Content: ownership and similarity; checked 2026-11-12) assign output rights between OpenAI and the user to the extent permitted by applicable law, and explain that output may not be unique. Contractual output rights and permission to distribute are separate from copyright protection or exclusivity. The owner remains responsible for supplied content and applicable third-party rights. No OpenAI endorsement is implied.

Asset integrity after the 2026-11-12 screenshot refresh:

- `background.png`: SHA-256 `103b6e2d447463d3f001277850017ad005eae8bb31cd25f0ed17d7659976ecc6`.
- `screenshot.png`: SHA-256 `8c4e56b6afe50fbaaf04cefa22149db146626597fad96d567033e71bf8e67961`.

## Local feature decoders

Pillow 12.3.0 declares MIT-CMU (installed License-Expression and LICENSE). SoundFile 0.14.0 declares BSD-3-Clause (installed metadata/LICENSE). These existing packages are now explicit CPU/GPU/test requirements for validated raster images and float WAV decoding; neither was installed or upgraded during this pass. SoundFile's underlying libsndfile and any bundled image/audio codec binaries have separate redistribution terms, which a future installer must review. This source-only change does not bundle those binaries.
