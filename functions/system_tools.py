from functions.console_tools import (
    execute_console_command,
    execute_console_command_declaration,
)
from functions.curl_tools import (
    execute_curl_command,
    execute_curl_command_declaration,
)
from functions.file_read_tools import (
    project_overview,
    project_overview_declaration,
    read_file,
    read_file_declaration,
)
from functions.file_write_tools import (
    write_file,
    write_file_declaration,
)
from functions.multi_tool_use_tools import (
    multi_tool_use_parallel,
    multi_tool_use_parallel_declaration,
)
from functions.rg_tools import (
    rg_list_files,
    rg_list_files_declaration,
    rg_search_text,
    rg_search_text_declaration,
)

tool_function_aliases = {
    "multi_tool_use_parallel": ["multi_tool_use.parallel"],
}

__all__ = [
    "execute_console_command",
    "execute_console_command_declaration",
    "execute_curl_command",
    "execute_curl_command_declaration",
    "project_overview",
    "project_overview_declaration",
    "read_file",
    "read_file_declaration",
    "rg_search_text",
    "rg_search_text_declaration",
    "rg_list_files",
    "rg_list_files_declaration",
    "multi_tool_use_parallel",
    "multi_tool_use_parallel_declaration",
    "write_file",
    "write_file_declaration",
]
