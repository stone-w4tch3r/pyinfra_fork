import shlex
from collections import defaultdict, namedtuple
from dataclasses import dataclass
from io import StringIO
from typing import Callable, Tuple, Dict, Set, List
from urllib.parse import urlparse

from pyinfra.facts.files import File
from pyinfra.facts.rpm import RpmPackage
from pyinfra.api import Host


@dataclass
class _Package:
    name: str
    version: str | None = None


def ensure_packages(
    host: Host,
    packages_to_ensure: str | list[str] | None,
    current_packages_to_versions: dict[str, set[str]],
    present: bool,
    install_command: str,
    uninstall_command: str,
    latest=False,
    upgrade_command: str = None,
    version_join: str = None,
    expand_package_fact: Callable[[str], list[str]] = None
):
    """
    Handles this common scenario:

    + We have a list of packages(/versions) to ensure
    + We have a map of existing package -> versions
    + We have the common command bits (install, uninstall, version "joiner")
    + Outputs commands to ensure our desired packages/versions
    + Optionally upgrades packages w/o specified version when present

    Args:
        packages_to_ensure: list of packages or package/versions
        current_packages_to_versions: fact returning dict of package names -> version
        present: whether packages should exist or not
        install_command: command to prefix to list of packages to install
        uninstall_command: as above for uninstalling packages
        latest: whether to upgrade installed packages when present
        upgrade_command: as above for upgrading
        version_join: the package manager specific "joiner", ie ``=`` for \
            ``<apt_pkg>=<version>``
    """

    if not packages_to_ensure:
        return

    current_packages = [
        _Package(name=name, version=version)
        for name, versions in current_packages_to_versions.items()
        for version in versions
    ]

    if isinstance(packages_to_ensure, str):
        packages_to_ensure = [packages_to_ensure]
    if version_join:
        packages = [
            _Package(name=package_with_version[0])
            if len(package_with_version) == 1
            else _Package(name=package_with_version[0], version=package_with_version[1])
            for package_with_version in [package.rsplit(version_join, 1) for package in packages_to_ensure]
        ]
    else:
        packages = [_Package(name=package) for package in packages_to_ensure]

    # if expand_package_fact:
    #     # todo: can expand_package_fact return None?
    #     current_packages = [
    #         _Package(name=pkg_name, version="VERSION_HERE")  # todo: version
    #         for pkg in current_packages
    #         for pkg_name in expand_package_fact(pkg.name)
    #     ]

    diff_packages: list[_Package] = []
    diff_packages_with_versions: dict[_Package, dict[str, set[str] | None]] = {}
    upgrade_packages: list[_Package] = []

    if present is True:
        for package in packages:
            is_present, packages_with_versions = any(pkg in current_packages for pkg in packages_to_check)

            if not is_present:
                diff_packages.append(package)
                diff_packages_with_versions[package] = packages_with_versions
            else:
                # Present packages w/o version specified - for upgrade if latest
                upgrade_packages.append(package)

                if not latest:
                    if package.name in current_packages_to_versions:
                        host.noop(
                            "package {0} is installed ({1})".format(
                                package,
                                ", ".join(current_packages_to_versions[package.name]),
                            ),
                        )
                    else:
                        host.noop("package {0} is installed".format(package))

    if present is False:
        for package in packages:
            is_present, packages_with_versions = _is_package_in_current(
                package,
                current_packages_to_versions,
                expand_package_fact,
                all_expanded_packages_required=True,
            )

            if is_present:
                diff_packages.append(package)
                diff_packages_with_versions[package] = packages_with_versions
            else:
                host.noop("package {0} is not installed".format(package))

    if diff_packages:
        command = install_command if present else uninstall_command

        joined_packages = [
            package.name if package.version is None else f"{package.name}{version_join}{package.version}"
            for package in diff_packages
        ]

        yield "{0} {1}".format(
            command,
            " ".join([shlex.quote(pkg) for pkg in joined_packages]),
        )

        for package in diff_packages:  # add/remove from current packages
            pkg_name = package.name
            version = package.version if package.version else "unknown"

            if present:
                current_packages_to_versions[pkg_name] = {version}
                current_packages_to_versions.update(diff_packages_with_versions.get(pkg_name, {}))
            else:
                current_packages_to_versions.pop(pkg_name, None)
                for name in diff_packages_with_versions.get(pkg_name, {}):
                    current_packages_to_versions.pop(name, None)

    if latest and upgrade_command and upgrade_packages:
        yield "{0} {1}".format(
            upgrade_command,
            " ".join([shlex.quote(pkg.name) for pkg in upgrade_packages]),
        )


def ensure_rpm(state, host, files, source, present, package_manager_command):
    original_source = source

    # If source is a url
    if urlparse(source).scheme:
        # Generate a temp filename (with .rpm extension to please yum)
        temp_filename = "{0}.rpm".format(state.get_temp_filename(source))

        # Ensure it's downloaded
        yield from files.download(source, temp_filename)

        # Override the source with the downloaded file
        source = temp_filename

    # Check for file .rpm information
    info = host.get_fact(RpmPackage, name=source)
    exists = False

    # We have info!
    if info:
        current_package = host.get_fact(RpmPackage, name=info["name"])
        if current_package and current_package["version"] == info["version"]:
            exists = True

    # Package does not exist and we want?
    if present and not exists:
        # If we had info, always install
        if info:
            yield "rpm -i {0}".format(source)
            host.create_fact(RpmPackage, kwargs={"name": info["name"]}, data=info)

        # This happens if we download the package mid-deploy, so we have no info
        # but also don't know if it's installed. So check at runtime, otherwise
        # the install will fail.
        else:
            yield "rpm -q `rpm -qp {0}` 2> /dev/null || rpm -i {0}".format(source)

    # Package exists but we don't want?
    elif exists and not present:
        yield "{0} remove -y {1}".format(package_manager_command, info["name"])
        host.delete_fact(RpmPackage, kwargs={"name": info["name"]})

    else:
        host.noop(
            "rpm {0} is {1}".format(
                original_source,
                "installed" if present else "not installed",
            ),
        )


def ensure_yum_repo(
    state,
    host,
    files,
    name_or_url,
    baseurl,
    present,
    description,
    enabled,
    gpgcheck,
    gpgkey,
    repo_directory="/etc/yum.repos.d/",
    type_=None,
):
    url = None
    url_parts = urlparse(name_or_url)
    if url_parts.scheme:
        url = name_or_url
        name_or_url = url_parts.path.split("/")[-1]
        if name_or_url.endswith(".repo"):
            name_or_url = name_or_url[:-5]

    filename = "{0}{1}.repo".format(repo_directory, name_or_url)

    # If we don't want the repo, just remove any existing file
    if not present:
        yield from files.file(filename, present=False)
        return

    # If we're a URL, download the repo if it doesn't exist
    if url:
        if not host.get_fact(File, path=filename):
            yield from files.download(url, filename)
        return

    # Description defaults to name
    description = description or name_or_url

    # Build the repo file from string
    repo_lines = [
        "[{0}]".format(name_or_url),
        "name={0}".format(description),
        "baseurl={0}".format(baseurl),
        "enabled={0}".format(1 if enabled else 0),
        "gpgcheck={0}".format(1 if gpgcheck else 0),
    ]

    if type_:
        repo_lines.append("type={0}".format(type_))

    if gpgkey:
        repo_lines.append("gpgkey={0}".format(gpgkey))

    repo_lines.append("")
    repo = "\n".join(repo_lines)
    repo = StringIO(repo)

    # Ensure this is the file on the server
    yield from files.put(repo, filename)
