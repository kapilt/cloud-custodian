
import click


@click.group()
def cli():
    """multi account organization managemnet"""

    

@cli.command()
def status():
    """report on multi account status"""
    

@cli.command()
def enable():
    """enable feature on org accounts."""
    

if __name__ == '__main__':
    cli()
