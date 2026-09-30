# Chat mode classification — 2026-09-28

Removed the obsolete ImageChat category from Agent mode contracts, canvas menu ordering, configuration field labels, Provider mode selection, Companion selection, harness metadata/binding, public protocol selection, and provider execution adapters.

`chat` owns conversation, including supported image attachments. `image_generation` owns image generation. Other existing media capabilities are unchanged. Gemini chat no longer automatically requests image output modalities based on a separate chat category; its dedicated image generation path remains. Image input mapping and inline image response preservation remain tested.

The five matching Provider declarations in the local `config/modelProvider.json` were normalized to `chat` and deduplicated. No matching persisted node `config.json` or profile JSON was found under `C:/Project/memories`. No runtime alias for the removed category was added. Negative tests explicitly check rejection of the removed mode.

Validation:

- 272 focused Python tests passed across mode contracts, parameter mapping, Provider options, harnesses, multimodal message mapping, and image generation/public image protocols.
- 13 frontend schema/Provider selection tests and Vue typecheck passed; production build passed.
- One existing document-presence test (`test_standalone_generation_node_types_are_removed`) fails because `README.md` is absent from this checkout; it was excluded from the focused passing run without altering that unrelated test.
- Real Chrome right-click menu verified locally and through the public cloud Board: `chat` and `image_generation` remain, the removed category is absent, and chat harness nodes remain available. Local API checked all 22 Providers. Browser errors: none. Local artifacts: `.runtime/chat-mode/`.
- Local backend restarted while all graphs had zero active tasks; cloud static frontend updated and all 67 deployed files verified. Public frontend asset bytes match the local build. No live paid model/image-generation request was used for these checks.

Existing provider and test modules over 400 lines received localized deletions/contract changes; no new responsibility was added. New mode regression tests live separately in `tests/test_chat_mode_contract.py`.
