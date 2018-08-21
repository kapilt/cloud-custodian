
import click


@click.group()
def cli():
    """multi account organization managemnet"""


def common(f):
    f = click.option(
        '-a', '--accounts', multiple=True, default=None)(f)
    f = click.option(
        '-t', '--tags', multiple=True, default=None, help="Account tag filter")(f)
    f = click.option(
        '-r', '--region', default=None, multiple=True)(f)
    return f
    

@cli.command()
@common
def status():
    """report on multi account status"""
    

@cli.command()
@common
def enable():
    """enable feature on org accounts."""


@cli.command()
@common
def disable():
    """disable feature on org accounts."""


if __name__ == '__main__':
    cli()
