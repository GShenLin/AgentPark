class ChannelError(RuntimeError):
    pass


class ChannelConfigError(ChannelError):
    pass


class ChannelRuntimeError(ChannelError):
    pass
