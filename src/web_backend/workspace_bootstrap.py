from __future__ import annotations

from fastapi import Request

from .domain_base import DomainBase


class WorkspaceBootstrapDomain(DomainBase):
    """Build the immutable snapshot required to mount the workspace UI."""

    def get_workspace_bootstrap(self, request: Request = None) -> dict:
        startup = self.core.graph_api.get_startup_graph_config(request=request)
        graph_id = str(startup["graph_id"])
        graph_response = self.core.graph_api.get_graph(graph_id, request=request)
        graph = graph_response["graph"]
        remote_status = self.core.remote_api.get_remote_status(request=request)
        remotes = self.core.remote_api.list_remotes(request=request)
        providers = self.core.system_api.list_providers(request=request)
        nodes = self.core.node_ops.list_nodes()
        tools = self.core.node_ops.list_tools()
        graphs = self.core.graph_api.list_graphs(request=request)
        graph_profiles = self.core.profile_api.list_graph_profiles()
        theme = self.core.settings_api.get_settings_section("theme")
        mobile_pcs = self.core.mobile_api.list_mobile_pcs()
        interactions = self.core.user_interaction_api.list_user_interactions(request=request)
        return {
            "startup_graph": graph,
            "remote_status": remote_status,
            "remotes": remotes.get("remotes", []),
            "providers": providers.get("providers", []),
            "nodes": nodes.get("nodes", []),
            "tools": tools.get("tools", []),
            "graphs": graphs.get("graphs", []),
            "graph_profiles": graph_profiles.get("profiles", []),
            "theme": {
                "data": theme.get("data", {}),
                "active_preset_id": theme.get("active_preset_id", ""),
            },
            "mobile_pcs": mobile_pcs.get("pcs", []),
            "user_interactions": interactions.get("requests", []),
        }


__all__ = ["WorkspaceBootstrapDomain"]
