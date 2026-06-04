import json
import os


class AgentPlanUtils:
    def sanitize_agent_name(self, name):
        if not isinstance(name, str):
            return "Worker"
        name = name.strip()
        name = name.replace("\\", "_").replace("/", "_").replace(":", "_")
        name = name.replace("\n", " ").replace("\r", " ").strip()
        if not name:
            return "Worker"

        keep = []
        for ch in name:
            if ch.isalnum() or ch in ("_", "-", " "):
                keep.append(ch)
            else:
                keep.append("_")
        cleaned = "".join(keep).strip().replace(" ", "_")
        if not cleaned:
            cleaned = "Worker"
        return cleaned[:64]

    def build_agent_memory_path(self, agent_name, base_dir):
        safe = self.sanitize_agent_name(agent_name)
        # Create a subfolder for the agent to isolate memory and images
        agent_dir = os.path.join(base_dir, safe)
        os.makedirs(agent_dir, exist_ok=True)
        return os.path.join(agent_dir, f"{safe}.md")

    def dedupe_agents(self, agents):
        seen = set()
        deduped = []
        for a in agents:
            if not isinstance(a, dict):
                continue
            name = a.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            deduped.append(a)
        return deduped

    def unique_agent_name(self, name, used_names):
        candidate = self.sanitize_agent_name(name)
        if candidate not in used_names:
            return candidate
        i = 2
        while True:
            alt = f"{candidate}_{i}"
            if alt not in used_names:
                return alt
            i += 1

    def parse_first_json_object(self, text):
        if not isinstance(text, str) or not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            return None
