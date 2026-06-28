class NodeConfigError(RuntimeError):
    pass


class NodeConfigReadError(NodeConfigError):
    pass


class NodeConfigNotFoundError(NodeConfigReadError):
    pass


class NodeConfigFormatError(NodeConfigReadError):
    pass


class NodeConfigWriteError(NodeConfigError):
    pass
