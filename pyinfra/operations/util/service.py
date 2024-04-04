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
    is_running = statuses.get(name, None)

    # If we don't know the status, we need to check if it's up before starting
    # and/or restarting/reloading
    if is_running is None:
        yield (
            "if ({status_command}); then "
            "({stop_command}); ({restart_command}); ({reload_command}); "
            "else ({start_command}); fi"
        ).format(
            status_command=formatter.format(name, status_argument),
            start_command=(formatter.format(name, "start") if running is True else "true"),
            stop_command=(formatter.format(name, "stop") if running is False else "true"),
            restart_command=(formatter.format(name, "restart") if restarted else "true"),
            reload_command=(formatter.format(name, "reload") if reloaded else "true"),
        )
        statuses[name] = running

    else:
        # Need down but running
        if running is False:
            if is_running:
                yield formatter.format(name, "stop")
                statuses[name] = False
            else:
                host.noop("service {0} is stopped".format(name))

        # Need running but down
        if running is True:
            if not is_running:
                yield formatter.format(name, "start")
                statuses[name] = True
            else:
                host.noop("service {0} is running".format(name))

        # Only restart if the service is already running
        if restarted and is_running:
            yield formatter.format(name, "restart")

        # Only reload if the service is already reloaded
        if reloaded and is_running:
            yield formatter.format(name, "reload")

    # Always execute arbitrary commands as these may or may not rely on the service
    # being up or down
    if command:
        yield formatter.format(name, command)
