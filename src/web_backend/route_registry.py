from fastapi import FastAPI


class ApiRouteRegistry:
    ROUTES = [
        ("get", "/api/runs/{task_id}/subagents/{name}/memory", lambda core: core.agent_domain.get_subagent_memory),
        ("get", "/api/mobile/pcs", lambda core: core.mobile_api.list_mobile_pcs),
        ("get", "/api/mobile/pcs/{pc_id}/graphs", lambda core: core.mobile_api.list_mobile_graphs),
        ("get", "/api/mobile/pcs/{pc_id}/graphs/{graph_id}/nodes", lambda core: core.mobile_api.list_mobile_nodes),
        ("get", "/api/mobile/pcs/{pc_id}/graphs/{graph_id}/nodes/{node_id}/conversation", lambda core: core.mobile_api.get_mobile_node_conversation),
        ("post", "/api/mobile/pcs/{pc_id}/graphs/{graph_id}/nodes/{node_id}/messages", lambda core: core.mobile_api.send_mobile_node_message),
        ("post", "/api/runs/{task_id}/subagents/{name}/stop", lambda core: core.agent_domain.stop_subagent),
        ("get", "/api/paste-agent/config", lambda core: core.agent_domain.get_paste_agent_config),
        ("post", "/api/paste-agent/config", lambda core: core.agent_domain.update_paste_agent_config),
        ("get", "/api/config/prompts", lambda core: core.agent_domain.list_prompts),
        ("get", "/api/config/prompts/{filename}", lambda core: core.agent_domain.get_prompt),
        ("post", "/api/config/prompts", lambda core: core.agent_domain.save_prompt),
        ("get", "/api/tools", lambda core: core.node_ops.list_tools),
        ("get", "/api/nodes", lambda core: core.node_ops.list_nodes),
        ("get", "/api/nodes/templates/{type_id}", lambda core: core.node_ops.get_node_template),
        ("post", "/api/nodes/run", lambda core: core.node_ops.run_node),
        ("post", "/api/nodes/instances", lambda core: core.node_ops.create_node_instance),
        ("post", "/api/nodes/instances/{node_id}/rename", lambda core: core.node_ops.rename_node_instance),
        ("delete", "/api/nodes/instances/{node_id}", lambda core: core.node_ops.delete_node_instance),
        ("get", "/api/nodes/instances/configs", lambda core: core.node_ops.list_node_instance_configs),
        ("get", "/api/nodes/instances/{node_id}/memory", lambda core: core.node_ops.get_node_instance_memory),
        ("post", "/api/nodes/instances/{node_id}/config", lambda core: core.node_ops.update_node_instance_config),
        ("post", "/api/nodes/instances/{node_id}/state", lambda core: core.node_ops.set_node_instance_state),
        ("post", "/api/nodes/instances/{node_id}/control", lambda core: core.node_ops.control_node_instance),
        ("post", "/api/nodes/instances/{node_id}/pending", lambda core: core.node_ops.enqueue_node_instance_pending),
        ("post", "/api/nodes/instances/{node_id}/pending/pop", lambda core: core.node_ops.pop_node_instance_pending),
        ("post", "/api/nodes/run_async", lambda core: core.node_ops.run_node_async),
        ("get", "/api/nodes/run/{run_id}", lambda core: core.node_ops.get_node_run),
        ("post", "/api/nodes/run/{run_id}/stop", lambda core: core.graph_api.stop_node_run),
        ("post", "/api/graphs/{graph_id}/runner/start", lambda core: core.graph_api.start_graph_runner),
        ("get", "/api/graphs/{graph_id}/runner/status", lambda core: core.graph_api.get_graph_runner_status),
        ("post", "/api/graphs/{graph_id}/emit", lambda core: core.graph_api.emit_graph),
        ("get", "/api/graphs/startup/config", lambda core: core.graph_api.get_startup_graph_config),
        ("post", "/api/graphs/startup/config", lambda core: core.graph_api.set_startup_graph_config),
        ("post", "/api/events/emit", lambda core: core.graph_api.emit_event_by_key),
        ("post", "/api/integration/ue/build-success", lambda core: core.graph_api.notify_ue_build_success),
        ("post", "/api/ue/build-event", lambda core: core.graph_api.notify_ue_build_success),
        ("get", "/api/graphs", lambda core: core.graph_api.list_graphs),
        ("get", "/api/graphs/{graph_id}", lambda core: core.graph_api.get_graph),
        ("post", "/api/graphs/{graph_id}", lambda core: core.graph_api.save_graph),
        ("get", "/api/files", lambda core: core.system_api.list_files),
        ("get", "/api/files/read", lambda core: core.system_api.read_file),
        ("get", "/api/files/raw", lambda core: core.system_api.raw_file),
        ("post", "/api/files/upload", lambda core: core.system_api.upload_files),
        ("post", "/api/files/select-folder", lambda core: core.system_api.select_folder),
        ("post", "/api/files/write", lambda core: core.system_api.write_file),
        ("post", "/api/files/rename", lambda core: core.system_api.rename_file),
        ("post", "/api/files/delete", lambda core: core.system_api.delete_file),
        ("get", "/api/providers", lambda core: core.system_api.list_providers),
    ]

    @classmethod
    def register(cls, app: FastAPI, core: object) -> None:
        for method_name, path, resolver in cls.ROUTES:
            handler = resolver(core)
            getattr(app, method_name)(path)(handler)
