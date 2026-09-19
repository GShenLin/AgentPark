import json
import threading
import uuid

from src.runtime_cancellation import CancellationRequested, cancel_source_from_agent
from .contracts import ComputerUseError
from .service import ComputerUseService


_lock = threading.Lock()
_service = None


def dispatch(method, args, agent):
    global _service
    try:
        if agent is None:
            raise ComputerUseError('Computer Use requires an owning agent session.')
        with _lock:
            owner = getattr(agent, '_computer_use_owner', None)
            if owner is None:
                owner = uuid.uuid4().hex
                setattr(agent, '_computer_use_owner', owner)
            if _service is None:
                from .windows_backend import WindowsBackend
                _service = ComputerUseService(WindowsBackend())
        result = _service.call(method, owner, args, cancel_source_from_agent(agent))
        return json.dumps({'status': 'success', **result}, ensure_ascii=False)
    except CancellationRequested as exc:
        return json.dumps({'status': 'stopped', 'error': str(exc), 'next': 'Read current window state before retrying.'})
    except ComputerUseError as exc:
        return json.dumps({'status': 'error', 'error': str(exc), 'next': 'Read current window state before retrying.'}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({'status': 'exception', 'error': f'{type(exc).__name__}: {exc}'}, ensure_ascii=False)
