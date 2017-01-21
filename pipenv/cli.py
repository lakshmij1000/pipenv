import codecs
import json
import os
import sys

import click
import crayons
import delegator
import pexpect
import toml
import _pipfile as pipfile

from .project import Project
from .utils import convert_deps_from_pip, convert_deps_to_pip

__version__ = '0.1.5'


project = Project()


def ensure_latest_pip():
    # Ensure that pip is installed.
    c = delegator.run('{} install pip'.format(which_pip()))

    # Check if version is out of date.
    if 'however' in c.err:
        # If version is out of date, update.
        click.echo(crayons.yellow('Pip is out of date... updating to latest.'))
        c = delegator.run('{} install pip --upgrade'.format(which_pip()), block=False)
        click.echo(crayons.blue(c.out))



def do_where(virtualenv=False, bare=True):
    """Executes the where functionality."""

    if not virtualenv:
        location = project.pipfile_location

        if not bare:
            click.echo('Pipfile found at {}. Considering this to be the project home.'.format(crayons.green(location)))
        else:
            click.echo(location)

    else:
        location = project.virtualenv_location

        if not bare:
            click.echo('Virtualenv location: {}'.format(crayons.green(location)))
        else:
            click.echo(location)


def do_install_dependencies(dev=False, only=False, bare=False):
    """"Executes the install functionality."""

    # Load the Pipfile.
    p = pipfile.load(project.pipfile_location)
    lockfile = json.loads(p.freeze())

    # Install default dependencies, always.
    deps = lockfile['default'] if not only else {}

    # Add development deps if --dev was passed.
    if dev:
        deps.update(lockfile['develop'])

    # Convert the deps to pip-compatbile arguments.
    deps = convert_deps_to_pip(deps)

    # Actually install each dependency into the virtualenv.
    for package_name in deps:

        if not bare:
            click.echo('Installing {}...'.format(crayons.green(package_name)))

        c = delegator.run('{} install "{}"'.format(which_pip(), package_name),)

        if not bare:
            click.echo(crayons.blue(c.out))


def do_create_virtualenv():
    """Creates a virtualenv."""
    click.echo(crayons.yellow('Creating a virtualenv for this project...'))

    # Actually create the virtualenv.
    c = delegator.run(['virtualenv', project.virtualenv_location, '--prompt=({})'.format(project.name)], block=False)
    click.echo(crayons.blue(c.out))

    # Say where the virtualenv is.
    do_where(virtualenv=True, bare=False)


def do_lock():
    """Executes the freeze functionality."""

    click.echo(crayons.yellow('Assuring all dependencies from Pipfile are installed...'))

    # Purge the virtualenv, for development dependencies.
    do_purge(bare=True)

    click.echo(crayons.yellow('Locking {} dependencies...'.format(crayons.red('[dev-packages]'))))

    # Install only development dependencies.
    do_install_dependencies(dev=True, only=True, bare=True)

    # Load the Pipfile and generate a lockfile.
    p = pipfile.load(project.pipfile_location)
    lockfile = json.loads(p.freeze())

    # Pip freeze development dependencies.
    c = delegator.run('{} freeze'.format(which_pip()))

    # Add Development dependencies to lockfile.
    for dep in c.out.split('\n'):
        if dep:
            lockfile['develop'].update(convert_deps_from_pip(dep))


    # Purge the virtualenv.
    do_purge(bare=True)

    click.echo(crayons.yellow('Locking {} dependencies...'.format(crayons.red('[packages]'))))

    # Install only development dependencies.
    do_install_dependencies(bare=True)

    # Pip freeze default dependencies.
    c = delegator.run('{} freeze'.format(which_pip()))

    # Add default dependencies to lockfile.
    for dep in c.out.split('\n'):
        if dep:
            lockfile['default'].update(convert_deps_from_pip(dep))

    with open(project.lockfile_location, 'w') as f:
        f.write(json.dumps(lockfile, indent=4, separators=(',', ': ')))

    click.echo(crayons.yellow('Note: ') + 'your project now has only default {} installed.'.format(crayons.red('[packages]')))
    click.echo('To install {}, run: $ {}'.format(crayons.red('[dev-packages]'), crayons.green('pipenv install --dev')))


def activate_virtualenv(source=True):
    """Returns the string to activate a virtualenv."""
    if source:
        return 'source {}/bin/activate'.format(project.virtualenv_location)
    else:
        return '{}/bin/activate'.format(project.virtualenv_location)


def do_activate_virtualenv(bare=False):
    """Executes the activate virtualenv functionality."""
    if not bare:
        click.echo('To activate this project\'s virtualenv, run the following:\n $ {}'.format(crayons.red('pipenv shell')))
    else:
        click.echo(activate_virtualenv())


def do_purge(bare=False):
    """Executes the purge functionality."""
    freeze = delegator.run('{} freeze'.format(which_pip())).out
    installed = freeze.split()

    if not bare:
        click.echo('Found {} installed package(s), purging...'.format(len(installed)))
    command = '{} uninstall {} -y'.format(which_pip(), ' '.join(installed))
    c = delegator.run(command)

    if not bare:
        click.echo(crayons.blue(c.out))

        click.echo(crayons.yellow('Virtualenv now purged and fresh!'))


def do_init(dev=False, skip_virtualenv=False):
    """Executes the init functionality."""

    # Assert Pipfile exists.
    if not project.pipfile_exists:

        click.echo(crayons.yellow('Creating a Pipfile for this project...'))

        # Create the pipfile if it doesn't exist.
        project.create_pipfile()

        # Create the Pipfile.freeze too.
        click.echo(crayons.yellow('Creating a Pipfile.lock as well...'))
        do_lock()

    # Display where the Project is established.
    do_where(bare=False)

    if not project.virtualenv_exists:
        do_create_virtualenv()

    # Write out the lockfile if it doesn't exist.
    if project.lockfile_exists:

        # Open the lockfile.
        with codecs.open(project.lockfile_location, 'r') as f:
            lockfile = json.load(f)

        # Update the lockfile if it is out-of-date.
        p = pipfile.load(project.pipfile_location)

        # Check that the hash of the Lockfile matches the lockfile's hash.
        if not lockfile['_meta']['Pipfile-sha256'] == p.hash:
            click.echo(crayons.red('Pipfile.lock out of date, updating...'))

            do_lock()

        click.echo(crayons.yellow('Installing dependencies from Pipfile.lock...'))

    else:

        # Load the pipfile.
        click.echo(crayons.yellow('Installing dependencies from Pipfile...'))
        p = pipfile.load(project.pipfile_location)
        lockfile = json.loads(p.freeze())

    do_install_dependencies(dev=dev)

    # Write out the lockfile if it doesn't exist.
    if not project.lockfile_exists:
        click.echo(crayons.yellow('Pipfile.lock not found, creating...'))
        with codecs.open(project.lockfile_location, 'w', 'utf-8') as f:
            f.write(p.freeze())

    # Activate virtualenv instructions.
    do_activate_virtualenv()


def which_pip():
    """Returns the location of virtualenv-installed pip."""
    return os.sep.join([project.virtualenv_location] + ['bin/pip'])

def which_python():
    """Returns the location of virtualenv-installed Python."""
    return os.sep.join([project.virtualenv_location] + ['bin/python'])


def ensure_virtualenv():
    if not project.virtualenv_exists:
        do_create_virtualenv()

@click.group(invoke_without_command=True)
@click.option('--where', is_flag=True, default=False, help="Output project home information.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
@click.version_option(prog_name=crayons.yellow('pipenv'), version=__version__)
@click.pass_context
def cli(ctx, where=False, bare=False):
    if ctx.invoked_subcommand is None:
        if where:
            do_where(bare=bare)



@click.command(help="Installs a provided package and adds it to Pipfile, or (if none is given), installs all packages.")
@click.argument('package_name', default=False)
@click.option('--dev','-d', is_flag=True, default=False)
def install(package_name=False, dev=False):
    # Ensure that virtualenv is available.
    ensure_virtualenv()

    # Install all dependencies, if none was provided.
    if package_name is False:
        click.echo(crayons.yellow('No package provided, installing all dependencies.'))
        do_init(dev=dev)
        sys.exit(1)

    click.echo('Installing {}...'.format(crayons.green(package_name)))

    c = delegator.run('{} install "{}"'.format(which_pip(), package_name))
    click.echo(crayons.blue(c.out))

    # Ensure that package was successfully installed.
    try:
        assert c.return_code == 0
    except AssertionError:
        click.echo('{} An error occured while installing {}'.format(crayons.red('Error: '), crayons.green(package_name)))
        sys.exit(1)

    if dev:
        click.echo('Adding {} to Pipfile\'s [dev-packages]...'.format(crayons.green(package_name)))
    else:
        click.echo('Adding {} to Pipfile\'s [packages]...'.format(crayons.green(package_name)))

    # Add the package to the Pipfile.
    project.add_package_to_pipfile(package_name, dev)


@click.command(help="Un-installs a provided package and removes it from Pipfile, or (if none is given), un-installs all packages.")
@click.argument('package_name', default=False)
def uninstall(package_name=False):
    # Ensure that virtualenv is available.
    ensure_virtualenv()

    # Un-install all dependencies, if none was provided.
    if package_name is False:
        click.echo(crayons.yellow('No package provided, un-installing all dependencies.'))
        do_purge()
        sys.exit(1)

    click.echo('Un-installing {}...'.format(crayons.green(package_name)))

    c = delegator.run('{} uninstall {} -y'.format(which_pip(), package_name))
    click.echo(crayons.blue(c.out))

    click.echo('Removing {} from Pipfile...'.format(crayons.green(package_name)))
    project.remove_package_from_pipfile(package_name)


@click.command(help="Generates Pipfile.lock.")
def lock():
    do_lock()


@click.command(help="Spans a Python interpreter within the virtualenv.")
@click.argument('args', nargs=-1)
def python(args):
    # Ensure that virtualenv is available.
    ensure_virtualenv()

    # Spawn the Python process, and iteract with it.
    c = pexpect.spawn('{} {}'.format(which_python(), ' '.join(args)))
    c.interact()

@click.command(help="Spans a shell within the virtualenv.")
def shell():
    # Ensure that virtualenv is available.
    ensure_virtualenv()

    # Spawn the Python process, and iteract with it.
    shell = os.environ['SHELL']
    click.echo(crayons.yellow('Spawning virtualenv shell ({}).'.format(crayons.red(shell))))

    c = pexpect.spawn("{} -c '. {}; exec {} -i'".format(shell, activate_virtualenv(source=False), shell))
    c.send(activate_virtualenv() + '\n')

    # Interact with the new shell.
    c.interact()

@click.command(help="Checks PEP 508 markers provided in Pipfile.")
def check():
    click.echo(crayons.yellow('Checking PEP 508 requirements...'))

    # Load the Pipfile.
    p = pipfile.load(project.pipfile_location)

    # Assert the given requirements.
    p.assert_requirements()

@click.command(help="Updates pip to latest version, uninstalls all packages, and re-installs them to latest compatible versions.")
@click.option('--dev','-d', is_flag=True, default=False)
def update(dev=False):

    # Ensure that virtualenv is available.
    ensure_virtualenv()

    # Update pip to latest version.
    ensure_latest_pip()

    click.echo(crayons.yellow('Updating all dependencies from Pipfile...'))

    do_purge()
    do_init(dev=dev)

    click.echo(crayons.yellow('All dependencies are now up-to-date!'))


# Install click commands.
cli.add_command(install)
cli.add_command(uninstall)
cli.add_command(update)
cli.add_command(lock)
cli.add_command(python)
cli.add_command(check)
cli.add_command(shell)


if __name__ == '__main__':
    cli()
