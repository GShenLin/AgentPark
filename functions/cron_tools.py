"""Tools loaded on demand by the Cron skill."""
from src.cron.tools import cron_create, cron_delete, cron_list, cron_update
from src.cron.tool_schema import (
    cron_create_declaration,
    cron_delete_declaration,
    cron_list_declaration,
    cron_update_declaration,
)
