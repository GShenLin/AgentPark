from nodes.agent_node_contract import AGENT_CONFIG_SCHEMA
from nodes.claude_node.contract import CLAUDE_CONFIG_SCHEMA
from nodes.codex_node.contract import CODEX_CONFIG_SCHEMA
from nodes.image_matting_node import Node as ImageMattingNode
from nodes.model_generation_node import Node as ModelGenerationNode
from nodes.model_texture_generation_node import Node as ModelTextureGenerationNode
from nodes.video_change_person_node import Node as VideoChangePersonNode


def test_provider_id_fields_use_select_schema_contract():
    schemas = {
        "agent_node": AGENT_CONFIG_SCHEMA,
        "claude_node": CLAUDE_CONFIG_SCHEMA,
        "codex_node": CODEX_CONFIG_SCHEMA,
        "image_matting_node": ImageMattingNode.config_schema,
        "model_generation_node": ModelGenerationNode.config_schema,
        "model_texture_generation_node": ModelTextureGenerationNode.config_schema,
        "video_change_person_node": VideoChangePersonNode.config_schema,
    }

    for node_type, schema in schemas.items():
        provider_schema = schema["provider_id"]
        assert provider_schema["type"] == "select", node_type
        assert isinstance(provider_schema["options"], list), node_type
