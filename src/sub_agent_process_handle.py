
class SubAgentProcessHandle:
    def __init__(self, name, provider_id, memory_file_path, task, process, result_queue):
        self.name = name
        self.provider_id = provider_id
        self.memory_file_path = memory_file_path
        self.task = task
        self.process = process
        self.result_queue = result_queue
