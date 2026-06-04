from typing import Any

from src.message_protocol import envelope_preview, normalize_envelope


class NodeRouteParser:
    @staticmethod
    def parse_port_count(value: Any, default: int = 1) -> int:
        try:
            number = int(float(value))
        except Exception:
            number = default
        if number <= 0:
            return default
        return number

    @staticmethod
    def parse_port_index(value: Any) -> int | None:
        try:
            number = int(float(value))
        except Exception:
            return None
        if number < 0:
            return None
        return number

    @staticmethod
    def normalize_payload(value: Any, default_role: str = "assistant") -> dict:
        return normalize_envelope(value, default_role=default_role)

    @classmethod
    def parse_node_output(cls, output: Any) -> dict:
        if not isinstance(output, dict):
            raise ValueError("Node output must be an object containing routes")

        raw_routes = output.get("routes")
        if not isinstance(raw_routes, list):
            raise ValueError("Node output must include routes: list")

        suppress_output = bool(output.get("suppress_output"))

        deduped_routes: list[dict] = []
        seen: set[int] = set()
        for item in raw_routes:
            if not isinstance(item, dict):
                continue
            port_index = cls.parse_port_index(item.get("output_index"))
            if port_index is None or port_index in seen:
                continue
            if "payload" not in item:
                continue
            seen.add(port_index)
            deduped_routes.append(
                {
                    "output_index": port_index,
                    "payload": cls.normalize_payload(item.get("payload"), default_role="assistant"),
                }
            )
        if not deduped_routes and not suppress_output:
            raise ValueError("Node output routes must contain at least one valid route item")

        display_payload = output.get("display_message")
        if display_payload is None and "display" in output:
            display_payload = output.get("display")
        if display_payload is None and deduped_routes:
            display_payload = deduped_routes[0]["payload"]
        if display_payload is None:
            display_payload = ""
        display_env = cls.normalize_payload(display_payload, default_role="assistant")

        return {
            "display_text": envelope_preview(display_env),
            "display_message": display_env,
            "routes": deduped_routes,
        }
