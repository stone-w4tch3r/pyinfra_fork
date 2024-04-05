from pyinfra.api import Host


def handle_service_control(
    host: Host,
    name: str,
    statuses: dict[str, bool],
    formatter: str,
    running: bool = None,
    restarted: bool = None,
    reloaded: bool = None,
    command: str = None,
    status_argument="status",
):
    status = statuses.get(name, None)

    # Need down but running
    if running is False:
        if status:
            yield formatter.format(name, "stop")
        else:
            host.noop("service {0} is stopped".format(name))

    # Need running but down
    if running is True:
        if not status:
            yield formatter.format(name, "start")
        else:
            host.noop("service {0} is running".format(name))

    # Only restart if the service is already running
    if restarted and status:
        yield formatter.format(name, "restart")

    # Only reload if the service is already reloaded
    if reloaded and status:
        yield formatter.format(name, "reload")

    # Always execute arbitrary commands as these may or may not rely on the service
    # being up or down
    if command:
        yield formatter.format(name, command)
