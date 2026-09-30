---
name: imagegen_gpt_official
description: Generate a new image or edit local images through AgentPark's shared Codex OAuth image endpoint.
---

# Image generation

Use this skill when the user asks to generate or edit a raster image.

## Tool

Call `skill__imagegen_gpt_official__image_gen` directly.

Arguments:

- `prompt`: required, detailed generation or editing instructions.
- `referenced_image_paths`: optional local image paths. Omit it when generating a new image.

The tool uses AgentPark's shared Codex OAuth authorization. Never ask for
`OPENAI_API_KEY` or a provider ID.

After success, return the absolute `image_path` produced by the tool and render
that image in the final response. Generated files are stored under the current
node's `generated_images` directory. If the tool returns an error, report the real
error without hiding it or claiming that an image was generated.
